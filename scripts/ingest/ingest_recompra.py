"""Baixa programas de recompra de ações e faz upsert no banco local."""
import io
import zipfile
import pandas as pd
from utils import get_db, watchlist_cnpjs, _http_get, _int, _float, upsert

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/EVENTOS/RECOMPRA_ACOES/DADOS"

def download() -> dict[str, pd.DataFrame]:
    url = f"{BASE_URL}/cia_aberta_recompra_acoes.zip"
    print(f"Baixando {url}...")
    r = _http_get(url, timeout=120)
    dfs = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if not name.endswith(".csv") or ".." in name or name.startswith("/"):
                continue
            key = "quantidades" if "quantidades" in name else \
                  "intermediarios" if "intermediarios" in name else "programas"
            with z.open(name) as f:
                dfs[key] = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return dfs

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
    conn  = get_db()
    cnpjs = watchlist_cnpjs()
    dfs   = download()

    if "programas" in dfs:
        rows = process_programas(dfs["programas"], cnpjs)
        upsert(conn, "recompra_programas", rows, "id_programa")

if __name__ == "__main__":
    main()
