"""Popula a tabela companies a partir do watchlist.csv."""
import csv
from pathlib import Path
from utils import get_supabase

WATCHLIST = Path(__file__).parents[2] / "watchlist.csv"

def main():
    sb = get_supabase()
    rows = []
    with open(WATCHLIST, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["cnpj"] == "VERIFICAR":
                print(f"SKIP {r['ticker']} — CNPJ pendente de verificação")
                continue
            rows.append({
                "cnpj":       r["cnpj"],
                "ticker":     r["ticker"],
                "codigo_cvm": r["codigo_cvm"] or None,
                "nome_cvm":   r["nome_cvm"],
                "setor":      r["setor"],
                "status_cvm": r["status_cvm"],
                "observacao": r["observacao"] or None,
            })

    result = sb.table("companies").upsert(rows, on_conflict="cnpj").execute()
    print(f"Upserted {len(rows)} empresas")

if __name__ == "__main__":
    main()
