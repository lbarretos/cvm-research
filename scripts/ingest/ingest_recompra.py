"""Baixa programas de recompra de ações e faz upsert no Supabase."""
import io
import zipfile
import httpx
import pandas as pd
from utils import get_supabase, watchlist_cnpjs

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/EVENTOS/RECOMPRA_ACOES/DADOS"

def download() -> dict[str, pd.DataFrame]:
    url = f"{BASE_URL}/cia_aberta_recompra_acoes.zip"
    print(f"Baixando {url}...")
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    dfs = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if name.endswith(".csv"):
                key = "quantidades" if "quantidades" in name else \
                      "intermediarios" if "intermediarios" in name else "programas"
                with z.open(name) as f:
                    dfs[key] = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return dfs

def _int(v):
    try: return int(float(str(v).replace(",", ".")))
    except: return None

def _float(v):
    try: return float(str(v).replace(",", "."))
    except: return None

def process_programas(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)].copy()
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "id_programa":                    _int(r.get("ID_Programa")),
            "cnpj_companhia":                 r["CNPJ_Companhia"],
            "nome_companhia":                 r.get("Nome_Companhia"),
            "quantidade_acoes_ordinarias":    _int(r.get("Quantidade_Acoes_Ordinarias")),
            "quantidade_acoes_preferenciais": _int(r.get("Quantidade_Acoes_Preferenciais")),
            "finalidade_compra":              r.get("Finalidade_Compra"),
            "data_deliberacao":               r.get("Data_Deliberacao") or None,
            "motivo":                         r.get("Motivo"),
            "data_final_prazo":               r.get("Data_Final_Prazo") or None,
            "situacao":                       r.get("Situacao"),
        })
    return rows

def main():
    sb    = get_supabase()
    cnpjs = watchlist_cnpjs()
    dfs   = download()

    if "programas" in dfs:
        rows = process_programas(dfs["programas"], cnpjs)
        for i in range(0, len(rows), 500):
            sb.table("recompra_programas").upsert(
                rows[i:i+500], on_conflict="id_programa"
            ).execute()
        print(f"recompra_programas: {len(rows)} rows")

if __name__ == "__main__":
    main()
