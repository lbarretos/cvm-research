"""
Extrai texto de PDFs do IPE para documentos da watchlist sem texto_extraido.
Fluxo: baixa PDF em memória → extrai texto → salva no banco → descarta PDF.
Nenhum byte de PDF é persistido em disco ou storage.

Uso:
  python extract_pdf.py                              # processa todos pendentes da watchlist
  python extract_pdf.py --cnpj 02.286.479/0001-08   # só uma empresa
  python extract_pdf.py --categoria "Fato Relevante" --limite 100
  python extract_pdf.py --categoria "Dados Econômico-Financeiros" --tipo "Press-release" --cnpj 16.670.085/0001-55 --limite 50
  python extract_pdf.py --categoria "Reunião da Administração"   # atas de conselho (dividendos, JCP)
  python extract_pdf.py --retry-failed               # re-tenta falhas anteriores
  python extract_pdf.py --rebuild-fts                # só reconstrói o índice FTS5

Requer DATABASE_URL=sqlite:///cvm_research.db no .env.
"""
import argparse
import io
import os
import sqlite3
import time
from datetime import datetime, timezone
import httpx
import pdfplumber
from utils import get_db, repair_pdf_text, watchlist_cnpjs
from qualidade_texto import avaliar_documento

# categoria → tipos aceitos (None = todos os tipos da categoria).
# Não existe categoria "Resultado": o release de resultados é 'Dados Econômico-Financeiros'
# com tipo 'Press-release'; os demais tipos dela são DFs completas, laudos e relatórios de
# rating/agente fiduciário, longos e já cobertos por demonstrativos_contabeis/notas_explicativas.
CATEGORIAS_PRIORITARIAS: dict[str, set[str] | None] = {
    "Fato Relevante": None,
    "Assembleia": None,
    "Comunicado ao Mercado": None,
    "Aviso aos Acionistas": None,
    "Reunião da Administração": None,   # atas de RCA: dividendos, JCP, recompra
    "Dados Econômico-Financeiros": {"Press-release"},
}

DF_TIPOS: set[str] = {
    "Demonstrações Financeiras Anuais Completas",
    "Demonstrações Financeiras Intermediárias",
    "Demonstrações Financeiras em Padrões Internacionais",
    "Demonstrações Financeiras Adicionais",
}

CREDITO_TIPOS: set[str] = {
    "Relatório de Agente Fiduciário",
    "Relatório de Agência de Rating",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CVM-Research-Bot/1.0)",
}


# ── Download e extração de texto ──────────────────────────────────────────────

def pdf_bytes_text(conteudo: bytes, usar_ocr: bool = False, max_ocr_paginas: int = 30) -> str | None:
    """Bytes de um PDF → texto reparado com páginas unidas por \f (None se não for PDF ou sem texto)."""
    if not conteudo.startswith(b"%PDF"):
        return None
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    if not any(p.strip() for p in pages):
        if usar_ocr:
            from ocr_fallback import ocr_pdf_completo
            pages = ocr_pdf_completo(conteudo, max_paginas=max_ocr_paginas)
        if not any(p.strip() for p in pages):
            return None
    elif usar_ocr:
        from ocr_fallback import reparar_paginas_com_ocr
        pages, reparadas = reparar_paginas_com_ocr(conteudo, pages, max_paginas=max_ocr_paginas)
        if reparadas > 0:
            print(f"      [OCR] {reparadas} página(s) recuperada(s) via tesseract")

    texto = repair_pdf_text("\f".join(pages))
    # Remove NUL bytes — SQLite rejeita strings com NUL
    return texto.replace("\x00", "")


def fetch_pdf_text(url: str, dominios: tuple[str, ...] | None = ("cvm.gov.br",),
                   usar_ocr: bool = False, max_ocr_paginas: int = 30) -> str | None:
    """`dominios`: onde o PDF pode estar depois dos redirects (o IPE só serve da CVM; os documentos
    de renda fixa também vêm da B3/Fundos.NET, ver ingest_rf_docs.py). None = qualquer host: só para
    link passado à mão pelo usuário."""
    try:
        r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
        r.raise_for_status()
        final_host = str(r.url.host)
        if dominios is not None and not any(final_host == d or final_host.endswith("." + d) for d in dominios):
            print(f"    SKIP: redirect para domínio fora de {dominios}: {final_host}")
            return None
        content_length = int(r.headers.get("content-length", 0))
        if content_length > 50 * 1024 * 1024:
            print(f"    SKIP: PDF muito grande ({content_length // 1024 // 1024}MB)")
            return None
        return pdf_bytes_text(r.content, usar_ocr=usar_ocr, max_ocr_paginas=max_ocr_paginas)
    except Exception as e:
        print(f"    ERRO fetch: {e}")
        return None


# ── Operações SQLite ──────────────────────────────────────────────────────────

def _fetch_pendentes(conn: sqlite3.Connection, cnpjs: set,
                     categorias: dict[str, set[str] | None],
                     limite: int, retry_failed: bool = False,
                     protocolo: str | None = None,
                     reextrair_ruins: bool = False) -> list[dict]:
    """Retorna documentos para extração/re-extração conforme filtros fornecidos."""
    if protocolo:
        cur = conn.execute(
            """
            SELECT protocolo_entrega, cnpj_companhia, categoria, assunto, link_download
            FROM ipe_docs
            WHERE protocolo_entrega = ?
            """,
            (protocolo,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    cnpjs_list = list(cnpjs)
    if not cnpjs_list or not categorias:
        return []

    cnpj_ph = ",".join("?" * len(cnpjs_list))
    filtros, filtro_params = [], []
    for categoria, tipos in categorias.items():
        if tipos is None:
            filtros.append("categoria = ?")
            filtro_params.append(categoria)
        else:
            filtros.append(f"(categoria = ? AND tipo IN ({','.join('?' * len(tipos))}))")
            filtro_params.extend([categoria, *sorted(tipos)])

    if reextrair_ruins:
        cond_filtro = "qualidade = 'ruim' AND texto_extraido IS NOT NULL"
        params = [*cnpjs_list, *filtro_params, limite]
    else:
        cond_filtro = "texto_extraido IS NULL AND extracao_falhou = ?"
        falhou_val = 1 if retry_failed else 0
        params = [falhou_val, *cnpjs_list, *filtro_params, limite]

    sql = f"""
        SELECT protocolo_entrega, cnpj_companhia, categoria, assunto, link_download
        FROM ipe_docs
        WHERE {cond_filtro}
          AND cnpj_companhia IN ({cnpj_ph})
          AND ({" OR ".join(filtros)})
        ORDER BY data_entrega DESC
        LIMIT ?
    """
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _salvar(conn: sqlite3.Connection, protocolo: str, texto: str | None) -> None:
    """Persiste texto extraído (ou marca falha) no banco SQLite, com métrica de qualidade."""
    now = datetime.now(timezone.utc).isoformat()
    if texto:
        qualidade, texto_qualidade = avaliar_documento(texto)
        conn.execute(
            """
            UPDATE ipe_docs
               SET texto_extraido  = ?,
                   chars_extraidos = ?,
                   qualidade       = ?,
                   texto_qualidade = ?,
                   extraido_em     = ?,
                   extracao_falhou = 0
             WHERE protocolo_entrega = ?
            """,
            (texto, len(texto), qualidade, texto_qualidade, now, protocolo),
        )
    else:
        conn.execute(
            "UPDATE ipe_docs SET extracao_falhou = 1, qualidade = 'ruim' WHERE protocolo_entrega = ?",
            (protocolo,),
        )
    conn.commit()


def _rebuild_fts(conn: sqlite3.Connection) -> None:
    """Reconstrói o índice FTS5 (ipe_docs_fts) a partir do conteúdo atual de ipe_docs."""
    print("Reconstruindo índice FTS5...")
    conn.execute("INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild')")
    conn.commit()
    print("  FTS5 reconstruído.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(cnpj_filter=None, categoria_filter=None, limite=200,
         retry_failed=False, rebuild_fts=False, tipo_filter=None, sem_fts=False,
         so_df=False, usar_ocr=False, max_ocr_paginas=30, protocolo=None,
         reextrair_ruins=False, so_credito=False):
    conn = get_db()

    if rebuild_fts:
        _rebuild_fts(conn)
        return

    if usar_ocr:
        from ocr_fallback import ocr_disponivel
        if not ocr_disponivel():
            print("  AVISO: --ocr solicitado mas tesseract não está pronto. Continuando sem OCR.")
            usar_ocr = False

    cnpjs  = {cnpj_filter} if cnpj_filter else watchlist_cnpjs()
    if so_df:
        cats = {"Dados Econômico-Financeiros": DF_TIPOS}
    elif so_credito:
        cats = {"Dados Econômico-Financeiros": CREDITO_TIPOS}
    elif categoria_filter:
        cats = {categoria_filter: {tipo_filter} if tipo_filter else None}
    else:
        cats = CATEGORIAS_PRIORITARIAS
    modo   = " [retry falhas anteriores]" if retry_failed else ""
    if reextrair_ruins:
        modo = " [re-extraindo documentos ruins]"
    ocr_str = " [OCR ativo]" if usar_ocr else ""
    print(f"Backend: SQLite local{modo}{ocr_str}")
    if protocolo:
        print(f"Documento alvo: {protocolo}")
    else:
        print(f"Empresas: {len(cnpjs)} | Categorias: "
              + ", ".join(c if t is None else f"{c} ({', '.join(sorted(t))})"
                          for c, t in sorted(cats.items())))

    docs = _fetch_pendentes(conn, cnpjs, cats, limite, retry_failed,
                            protocolo=protocolo, reextrair_ruins=reextrair_ruins)
    print(f"Documentos a processar: {len(docs)}")

    ok = fail = skip = 0
    for doc in docs:
        url = doc.get("link_download")
        if not url:
            skip += 1
            continue

        assunto = (doc.get("assunto") or "")[:60]
        print(f"  [{doc['cnpj_companhia']}] {doc['categoria']} — {assunto}...")
        texto = fetch_pdf_text(url, usar_ocr=usar_ocr, max_ocr_paginas=max_ocr_paginas)
        time.sleep(0.5)  # respeita rate limit do portal CVM

        sucesso = texto and len(texto) > 100
        _salvar(conn, doc["protocolo_entrega"], texto if sucesso else None)

        if sucesso:
            ok += 1
        else:
            fail += 1

    print(f"\nResultado: {ok} extraídos | {fail} falhas | {skip} sem link")

    if ok > 0 and not sem_fts:
        print()
        _rebuild_fts(conn)
        print("  Busca full-text disponível via ipe_docs_fts.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Extrai texto de PDFs do IPE e popula texto_extraido no banco."
    )
    p.add_argument("--cnpj",            help="Filtrar por CNPJ")
    p.add_argument("--protocolo",       help="Processar um documento específico por protocolo de entrega")
    p.add_argument("--categoria",       help="Filtrar por categoria")
    p.add_argument("--tipo",            help="Com --categoria: filtrar também por tipo (ex: Press-release)")
    p.add_argument("--so-df",           action="store_true",
                   help="Extrai apenas DFs (Anuais Completas, Intermediárias, Internacionais, Adicionais)")
    p.add_argument("--so-credito",      action="store_true",
                   help="Extrai apenas documentos de crédito (Relatório de Agente Fiduciário e Relatório de Agência de Rating)")
    p.add_argument("--ocr",             action="store_true",
                   help="Habilita fallback de OCR (via tesseract) para páginas com fontes corrompidas (Identity-H) ou escaneadas")
    p.add_argument("--max-ocr-paginas", type=int, default=30,
                   help="Teto máximo de páginas com OCR por documento (default: 30)")
    p.add_argument("--reextrair-ruins", action="store_true",
                   help="Re-extrai documentos com qualidade='ruim' (combinar com --ocr)")
    p.add_argument("--limite",          type=int, default=200,
                   help="Máximo de documentos a processar (default: 200)")
    p.add_argument("--retry-failed",    action="store_true",
                   help="Re-tentar docs marcados como falha (útil para erros transitórios)")
    p.add_argument("--rebuild-fts",     action="store_true",
                   help="Apenas reconstrói o índice FTS5 sem baixar nenhum PDF")
    p.add_argument("--sem-fts",         action="store_true",
                   help="Não reconstrói o índice FTS5 ao fim (um laço de lotes reconstrói uma vez só, no fim)")
    args = p.parse_args()
    if args.tipo and not args.categoria:
        p.error("--tipo exige --categoria")
    if args.so_df and args.categoria:
        p.error("--so-df não pode ser combinada com --categoria")
    if args.so_credito and (args.categoria or args.so_df):
        p.error("--so-credito não pode ser combinada com --categoria ou --so-df")
    main(args.cnpj, args.categoria, args.limite, args.retry_failed, args.rebuild_fts, args.tipo,
         args.sem_fts, args.so_df, args.ocr, args.max_ocr_paginas, args.protocolo,
         args.reextrair_ruins, args.so_credito)
