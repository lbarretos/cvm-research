import csv
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

WATCHLIST_PATH = Path(__file__).parents[2] / "watchlist.csv"

def load_watchlist() -> dict[str, dict]:
    """Retorna dict cnpj -> {ticker, codigo_cvm, nome_cvm, setor}."""
    watchlist = {}
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["cnpj"] == "VERIFICAR":
                continue
            watchlist[row["cnpj"]] = {
                "ticker":      row["ticker"],
                "codigo_cvm":  row["codigo_cvm"],
                "nome_cvm":    row["nome_cvm"],
                "setor":       row["setor"],
                "status_cvm":  row["status_cvm"],
            }
    return watchlist

def watchlist_cnpjs() -> set[str]:
    return set(load_watchlist().keys())

def get_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)
