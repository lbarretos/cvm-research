"""
Extrai texto de PDFs do IPE para documentos da watchlist sem texto_extraido.
Fluxo: baixa PDF em memória → extrai texto → salva no Supabase → descarta PDF.
Nenhum byte de PDF é persistido em disco ou storage.

Uso:
  python extract_pdf.py                        # processa todos pendentes da watchlist
  python extract_pdf.py --cnpj 02.286.479/0001-08   # só uma empresa
  python extract_pdf.py --categoria "Fato Relevante" --limite 100
"""
import argparse
import io
import time
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
        if "application/pdf" not in r.headers.get("content-type", ""):
            return None
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n\n".join(p for p in pages if p.strip())
    except Exception as e:
        print(f"    ERRO fetch: {e}")
        return None

def main(cnpj_filter=None, categoria_filter=None, limite=200):
    sb    = get_supabase()
    cnpjs = {cnpj_filter} if cnpj_filter else watchlist_cnpjs()

    query = (
        sb.table("ipe_docs")
          .select("protocolo_entrega, cnpj_companhia, categoria, assunto, link_download")
          .is_("texto_extraido", "null")
          .eq("extracao_falhou", False)
          .in_("cnpj_companhia", list(cnpjs))
          .in_("categoria", list(CATEGORIAS_PRIORITARIAS if not categoria_filter else {categoria_filter}))
          .order("data_entrega", desc=True)
          .limit(limite)
    )
    docs = query.execute().data
    print(f"Pendentes para extração: {len(docs)}")

    ok = fail = skip = 0
    for doc in docs:
        url = doc.get("link_download")
        if not url:
            skip += 1
            continue

        print(f"  [{doc['cnpj_companhia']}] {doc['categoria']} — {doc['assunto'][:60] if doc['assunto'] else ''}...")
        texto = fetch_pdf_text(url)
        time.sleep(0.5)  # respeita rate limit do portal CVM

        if texto and len(texto) > 100:
            sb.table("ipe_docs").update({
                "texto_extraido": texto,
                "chars_extraidos": len(texto),
                "extraido_em": "NOW()",
                "extracao_falhou": False,
            }).eq("protocolo_entrega", doc["protocolo_entrega"]).execute()
            ok += 1
        else:
            sb.table("ipe_docs").update({
                "extracao_falhou": True,
            }).eq("protocolo_entrega", doc["protocolo_entrega"]).execute()
            fail += 1

    print(f"\nResultado: {ok} extraídos | {fail} falhas | {skip} sem link")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cnpj",      help="Filtrar por CNPJ")
    p.add_argument("--categoria", help="Filtrar por categoria")
    p.add_argument("--limite",    type=int, default=200)
    args = p.parse_args()
    main(args.cnpj, args.categoria, args.limite)
