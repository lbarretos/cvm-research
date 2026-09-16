"""
Extrai o texto das Notas Explicativas de ITR/DFP da CVM.

Por que este script existe: demonstrativos_contabeis (ingest_dfp.py /
ingest_itr.py) só tem os quadros padronizados (BPA/BPP/DRE/DFC_MI/DVA) — sem
notas explicativas. Confirmado por inspeção manual do pacote ZIP oficial de um
ITR (Frasle 1T26, NumeroSequencialDocumento=156792): o XML embutido
("006211ITR31-03-2026v2.xml") usa o mesmo schema Conta/CodigoConta/Valor já
normalizado no banco — não é XBRL e não tem nenhum bloco de nota. As notas só
existem no PDF completo embutido no mesmo pacote (mesmo documento publicado em
sites de RI como mziq.com).

Fluxo: utils.fetch_doc_metadata() dá o NumeroSequencialDocumento por
(cnpj, data_referencia) → baixa o ZIP do pacote em memória → extrai o PDF
embutido em memória → extrai texto com pdfplumber → salva no banco → descarta
os bytes. Nenhum PDF é persistido em disco (mesma política de extract_pdf.py).

Uso:
  python ingest_notas_explicativas.py --cnpj 88.610.126/0001-29 --ano 2026 --fonte ITR
  python ingest_notas_explicativas.py --ano 2025 --fonte DFP
  python ingest_notas_explicativas.py --ano 2025 --fonte ITR --limite 20
  python ingest_notas_explicativas.py --retry-failed
  python ingest_notas_explicativas.py --rebuild-fts

Requer DATABASE_URL=sqlite:///cvm_research.db no .env.
"""
import argparse
import io
import time
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import pdfplumber

from utils import _http_get, fetch_doc_metadata, get_db, watchlist_cnpjs

DOWNLOAD_URL = (
    "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
    "?CodigoInstituicao=1&NumeroSequencialDocumento={numero}"
)


def latest_por_periodo(df_meta: pd.DataFrame, cnpjs: set, fonte: str) -> list[dict]:
    """
    Reduz o CSV de metadados (ver utils.fetch_doc_metadata) a 1 linha por
    (cnpj, data_referencia): a maior VERSAO — igual à lógica já usada nas
    queries de demonstrativos_contabeis (CLAUDE.md, seção "DRE linha a linha").
    """
    df = df_meta[df_meta["CNPJ_CIA"].isin(cnpjs)].copy()
    if df.empty:
        return []
    df["VERSAO"] = df["VERSAO"].astype(int)
    df["ID_DOC"] = df["ID_DOC"].astype(int)
    df = df.sort_values("VERSAO").drop_duplicates(
        subset=["CNPJ_CIA", "DT_REFER"], keep="last"
    )
    return [
        {
            "cnpj_companhia": r["CNPJ_CIA"],
            "fonte": fonte,
            "data_referencia": r["DT_REFER"],
            "versao": int(r["VERSAO"]),
            "numero_sequencial_documento": int(r["ID_DOC"]),
        }
        for _, r in df.iterrows()
    ]


def extrair_pdf_do_pacote(zip_bytes: bytes) -> bytes | None:
    """Retorna os bytes do primeiro .pdf dentro do pacote ZIP do documento."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        pdf_names = [n for n in z.namelist() if n.lower().endswith(".pdf")]
        if not pdf_names:
            return None
        return z.read(pdf_names[0])


def fetch_notas_texto(numero_sequencial: int) -> str | None:
    """
    Baixa o pacote ZIP completo do documento (ITR/DFP) via NumeroSequencialDocumento
    e extrai o texto do PDF embutido — único lugar onde as notas explicativas
    existem (ver docstring do módulo).
    """
    url = DOWNLOAD_URL.format(numero=numero_sequencial)
    try:
        r = _http_get(url, timeout=120)
        pdf_bytes = extrair_pdf_do_pacote(r.content)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            return None
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        texto = "\n\n".join(p for p in pages if p.strip())
        return texto.replace("\x00", "")
    except Exception as e:
        print(f"    ERRO fetch (doc {numero_sequencial}): {e}")
        return None


def _upsert_pendente_rows(conn, rows: list[dict]) -> None:
    """
    Garante 1 linha por (cnpj, fonte, data_referencia) antes de extrair.
    Se a VERSAO subiu desde a última vez (reapresentação), reseta
    texto_extraido/extracao_falhou para forçar reprocessamento.
    """
    for row in rows:
        conn.execute(
            """
            INSERT INTO notas_explicativas
                (cnpj_companhia, fonte, data_referencia, versao, numero_sequencial_documento)
            VALUES (:cnpj_companhia, :fonte, :data_referencia, :versao, :numero_sequencial_documento)
            ON CONFLICT (cnpj_companhia, fonte, data_referencia) DO UPDATE SET
                versao = excluded.versao,
                numero_sequencial_documento = excluded.numero_sequencial_documento,
                texto_extraido = CASE WHEN excluded.versao > notas_explicativas.versao
                                       THEN NULL ELSE notas_explicativas.texto_extraido END,
                extracao_falhou = CASE WHEN excluded.versao > notas_explicativas.versao
                                        THEN 0 ELSE notas_explicativas.extracao_falhou END,
                updated_at = datetime('now')
            """,
            row,
        )
    conn.commit()


def _fetch_pendentes(conn, cnpjs: set, fonte: str, ano: int, limite: int,
                      retry_failed: bool = False) -> list[dict]:
    """Retorna documentos sem texto_extraido para as empresas/fonte/ano dados."""
    falhou_val = 1 if retry_failed else 0
    cnpj_list = list(cnpjs)
    if not cnpj_list:
        return []
    cnpj_ph = ",".join("?" * len(cnpj_list))
    sql = f"""
        SELECT id, cnpj_companhia, data_referencia, numero_sequencial_documento
        FROM notas_explicativas
        WHERE texto_extraido IS NULL
          AND extracao_falhou = ?
          AND fonte = ?
          AND data_referencia LIKE ?
          AND cnpj_companhia IN ({cnpj_ph})
        ORDER BY data_referencia DESC
        LIMIT ?
    """
    params = [falhou_val, fonte, f"{ano}-%", *cnpj_list, limite]
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _salvar(conn, row_id: int, texto: str | None) -> None:
    """Persiste texto extraído (ou marca falha) no banco SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    if texto:
        conn.execute(
            """
            UPDATE notas_explicativas
               SET texto_extraido = ?, chars_extraidos = ?, extraido_em = ?, extracao_falhou = 0
             WHERE id = ?
            """,
            (texto, len(texto), now, row_id),
        )
    else:
        conn.execute(
            "UPDATE notas_explicativas SET extracao_falhou = 1 WHERE id = ?", (row_id,)
        )
    conn.commit()


if __name__ == "__main__":
    pass  # CLI adicionado em task futura
