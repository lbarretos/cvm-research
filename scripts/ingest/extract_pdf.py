"""
Extrai texto de PDFs do IPE para documentos da watchlist sem texto_extraido.
Fluxo: baixa PDF em memória → extrai texto → salva no banco → descarta PDF.
Nenhum byte de PDF é persistido em disco ou storage.

Uso:
  python extract_pdf.py                              # processa todos pendentes da watchlist
  python extract_pdf.py --cnpj 02.286.479/0001-08   # só uma empresa
  python extract_pdf.py --categoria "Fato Relevante" --limite 100
  python extract_pdf.py --categoria "Resultado" --cnpj 16.670.085/0001-55 --limite 50

Funciona com banco local (DATABASE_URL) ou Supabase (SUPABASE_URL + SUPABASE_KEY).
"""
import argparse
import io
import os
import sys
import time
from datetime import datetime, timezone
import httpx
import pdfplumber
from utils import get_supabase, watchlist_cnpjs

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
        # Remove NUL bytes (0x00) — PostgreSQL rejeita strings com NUL
        return texto.replace("\x00", "")
    except Exception as e:
        print(f"    ERRO fetch: {e}")
        return None


# ── backend psycopg2 ──────────────────────────────────────────────────────────

def _fetch_pendentes_pg(conn, cnpjs: set, categorias: set, limite: int,
                        retry_failed: bool = False) -> list[dict]:
    cnpjs_list = list(cnpjs)
    cats_list  = list(categorias)
    # retry_failed=True: re-tenta docs que falharam antes (ex: timeout transitório)
    # retry_failed=False: só docs nunca tentados
    falhou_filter = "TRUE"  if retry_failed else "FALSE"
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT protocolo_entrega, cnpj_companhia, categoria, assunto, link_download
            FROM ipe_docs
            WHERE texto_extraido IS NULL
              AND extracao_falhou = {falhou_filter}
              AND cnpj_companhia = ANY(%s)
              AND categoria      = ANY(%s)
            ORDER BY data_entrega DESC
            LIMIT %s
        """, (cnpjs_list, cats_list, limite))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _salvar_pg(conn, protocolo: str, texto: str | None) -> None:
    if texto:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ipe_docs
                SET texto_extraido  = %s,
                    chars_extraidos = %s,
                    extraido_em     = %s,
                    extracao_falhou = FALSE
                WHERE protocolo_entrega = %s
            """, (texto, len(texto), datetime.now(timezone.utc), protocolo))
    else:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ipe_docs SET extracao_falhou = TRUE
                WHERE protocolo_entrega = %s
            """, (protocolo,))
    conn.commit()


# ── backend Supabase ──────────────────────────────────────────────────────────

def _fetch_pendentes_sb(sb, cnpjs: set, categorias: set, limite: int) -> list[dict]:
    return (
        sb.table("ipe_docs")
          .select("protocolo_entrega, cnpj_companhia, categoria, assunto, link_download")
          .is_("texto_extraido", "null")
          .eq("extracao_falhou", False)
          .in_("cnpj_companhia", list(cnpjs))
          .in_("categoria", list(categorias))
          .order("data_entrega", desc=True)
          .limit(limite)
          .execute()
          .data
    )


def _salvar_sb(sb, protocolo: str, texto: str | None) -> None:
    if texto:
        sb.table("ipe_docs").update({
            "texto_extraido": texto,
            "chars_extraidos": len(texto),
            "extraido_em": datetime.now(timezone.utc).isoformat(),
            "extracao_falhou": False,
        }).eq("protocolo_entrega", protocolo).execute()
    else:
        sb.table("ipe_docs").update({
            "extracao_falhou": True,
        }).eq("protocolo_entrega", protocolo).execute()


# ── main ──────────────────────────────────────────────────────────────────────

def main(cnpj_filter=None, categoria_filter=None, limite=200, retry_failed=False):
    db     = get_supabase()   # retorna psycopg2 conn ou supabase client
    is_pg  = hasattr(db, "cursor")
    cnpjs  = {cnpj_filter} if cnpj_filter else watchlist_cnpjs()
    cats   = {categoria_filter} if categoria_filter else CATEGORIAS_PRIORITARIAS

    backend = "PostgreSQL local" if is_pg else "Supabase"
    modo    = " [retry falhas anteriores]" if retry_failed else ""
    print(f"Backend: {backend}{modo}")

    docs = _fetch_pendentes_pg(db, cnpjs, cats, limite, retry_failed) if is_pg \
           else _fetch_pendentes_sb(db, cnpjs, cats, limite)
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

        if texto and len(texto) > 100:
            if is_pg:
                _salvar_pg(db, doc["protocolo_entrega"], texto)
            else:
                _salvar_sb(db, doc["protocolo_entrega"], texto)
            ok += 1
        else:
            if is_pg:
                _salvar_pg(db, doc["protocolo_entrega"], None)
            else:
                _salvar_sb(db, doc["protocolo_entrega"], None)
            fail += 1

    print(f"\nResultado: {ok} extraídos | {fail} falhas | {skip} sem link")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cnpj",         help="Filtrar por CNPJ")
    p.add_argument("--categoria",    help="Filtrar por categoria")
    p.add_argument("--limite",       type=int, default=200)
    p.add_argument("--retry-failed", action="store_true",
                   help="Re-tentar docs marcados como falha (útil para erros transitórios)")
    args = p.parse_args()
    main(args.cnpj, args.categoria, args.limite, args.retry_failed)
