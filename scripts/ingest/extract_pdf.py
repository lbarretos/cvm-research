"""
Extrai texto de PDFs do IPE para documentos da watchlist sem texto_extraido.
Fluxo: baixa PDF em memória → extrai texto → salva no banco → descarta PDF.
Nenhum byte de PDF é persistido em disco ou storage.

Uso:
  python extract_pdf.py                              # processa todos pendentes da watchlist
  python extract_pdf.py --cnpj 02.286.479/0001-08   # só uma empresa
  python extract_pdf.py --categoria "Fato Relevante" --limite 100
  python extract_pdf.py --categoria "Resultado" --cnpj 16.670.085/0001-55 --limite 50
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
from utils import get_db, watchlist_cnpjs

CATEGORIAS_PRIORITARIAS = {
    "Fato Relevante",
    "Assembleia",
    "Comunicado ao Mercado",
    "Aviso aos Acionistas",
    "Resultado",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CVM-Research-Bot/1.0)",
}


# ── Download e extração de texto ──────────────────────────────────────────────

def fetch_pdf_text(url: str) -> str | None:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
        r.raise_for_status()
        final_host = str(r.url.host)
        if not (final_host.endswith(".cvm.gov.br") or final_host == "cvm.gov.br"):
            print(f"    SKIP: redirect para domínio não-CVM: {final_host}")
            return None
        content_length = int(r.headers.get("content-length", 0))
        if content_length > 50 * 1024 * 1024:
            print(f"    SKIP: PDF muito grande ({content_length // 1024 // 1024}MB)")
            return None
        if not r.content.startswith(b"%PDF"):
            return None
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        texto = "\n\n".join(p for p in pages if p.strip())
        # Remove NUL bytes — SQLite rejeita strings com NUL
        return texto.replace("\x00", "")
    except Exception as e:
        print(f"    ERRO fetch: {e}")
        return None


# ── Operações SQLite ──────────────────────────────────────────────────────────

def _fetch_pendentes(conn: sqlite3.Connection, cnpjs: set, categorias: set,
                     limite: int, retry_failed: bool = False) -> list[dict]:
    """Retorna documentos sem texto_extraido para as empresas e categorias fornecidas."""
    cnpjs_list = list(cnpjs)
    cats_list  = list(categorias)
    if not cnpjs_list or not cats_list:
        return []
    falhou_val = 1 if retry_failed else 0

    cnpj_ph = ",".join("?" * len(cnpjs_list))
    cat_ph  = ",".join("?" * len(cats_list))

    sql = f"""
        SELECT protocolo_entrega, cnpj_companhia, categoria, assunto, link_download
        FROM ipe_docs
        WHERE texto_extraido IS NULL
          AND extracao_falhou = ?
          AND cnpj_companhia IN ({cnpj_ph})
          AND categoria      IN ({cat_ph})
        ORDER BY data_entrega DESC
        LIMIT ?
    """
    params = [falhou_val, *cnpjs_list, *cats_list, limite]
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _salvar(conn: sqlite3.Connection, protocolo: str, texto: str | None) -> None:
    """Persiste texto extraído (ou marca falha) no banco SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    if texto:
        conn.execute(
            """
            UPDATE ipe_docs
               SET texto_extraido  = ?,
                   chars_extraidos = ?,
                   extraido_em     = ?,
                   extracao_falhou = 0
             WHERE protocolo_entrega = ?
            """,
            (texto, len(texto), now, protocolo),
        )
    else:
        conn.execute(
            "UPDATE ipe_docs SET extracao_falhou = 1 WHERE protocolo_entrega = ?",
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
         retry_failed=False, rebuild_fts=False):
    conn = get_db()

    if rebuild_fts:
        _rebuild_fts(conn)
        return

    cnpjs  = {cnpj_filter} if cnpj_filter else watchlist_cnpjs()
    cats   = {categoria_filter} if categoria_filter else CATEGORIAS_PRIORITARIAS
    modo   = " [retry falhas anteriores]" if retry_failed else ""
    print(f"Backend: SQLite local{modo}")
    print(f"Empresas: {len(cnpjs)} | Categorias: {sorted(cats)}")

    docs = _fetch_pendentes(conn, cnpjs, cats, limite, retry_failed)
    print(f"Pendentes para extração: {len(docs)}")

    ok = fail = skip = 0
    for doc in docs:
        url = doc.get("link_download")
        if not url:
            skip += 1
            continue

        assunto = (doc.get("assunto") or "")[:60]
        print(f"  [{doc['cnpj_companhia']}] {doc['categoria']} — {assunto}...")
        texto = fetch_pdf_text(url)
        time.sleep(0.5)  # respeita rate limit do portal CVM

        sucesso = texto and len(texto) > 100
        _salvar(conn, doc["protocolo_entrega"], texto if sucesso else None)

        if sucesso:
            ok += 1
        else:
            fail += 1

    print(f"\nResultado: {ok} extraídos | {fail} falhas | {skip} sem link")

    if ok > 0:
        print()
        _rebuild_fts(conn)
        print("  Busca full-text disponível via ipe_docs_fts.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Extrai texto de PDFs do IPE e popula texto_extraido no banco."
    )
    p.add_argument("--cnpj",         help="Filtrar por CNPJ")
    p.add_argument("--categoria",    help="Filtrar por categoria")
    p.add_argument("--limite",       type=int, default=200,
                   help="Máximo de documentos a processar (default: 200)")
    p.add_argument("--retry-failed", action="store_true",
                   help="Re-tentar docs marcados como falha (útil para erros transitórios)")
    p.add_argument("--rebuild-fts",  action="store_true",
                   help="Apenas reconstrói o índice FTS5 sem baixar nenhum PDF")
    args = p.parse_args()
    main(args.cnpj, args.categoria, args.limite, args.retry_failed, args.rebuild_fts)
