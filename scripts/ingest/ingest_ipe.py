"""
Baixa os CSVs anuais do IPE e faz upsert dos metadados no Supabase.
Não baixa nem armazena PDFs — apenas metadados + link_download.
"""
import io
import zipfile
from datetime import date
import httpx
import pandas as pd
from utils import get_supabase, watchlist_cnpjs, _http_get, _sanitize, upsert

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS"

# Só extrai texto para estas categorias (as demais ficam como metadado)
CATEGORIAS_EXTRAIR = {
    "Fato Relevante",
    "Assembleia",
    "Comunicado ao Mercado",
    "Aviso aos Acionistas",
    "Resultado",
}

def download_year(year: int) -> pd.DataFrame:
    url = f"{BASE_URL}/ipe_cia_aberta_{year}.zip"
    print(f"Baixando {url}...")
    r = _http_get(url, timeout=120)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        csv_name = next(
            n for n in z.namelist()
            if n.endswith(".csv") and ".." not in n and not n.startswith("/")
        )
        with z.open(csv_name) as f:
            df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return df

def process(df: pd.DataFrame, cnpjs: set[str]) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)].copy()
    df["Data_Referencia"] = pd.to_datetime(df["Data_Referencia"], errors="coerce").dt.date
    df["Data_Entrega"]    = pd.to_datetime(df["Data_Entrega"],    errors="coerce").dt.date
    df["Versao"]          = pd.to_numeric(df["Versao"], errors="coerce").fillna(1).astype(int)

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "protocolo_entrega":  r["Protocolo_Entrega"],
            "cnpj_companhia":     r["CNPJ_Companhia"],
            "nome_companhia":     r.get("Nome_Companhia"),
            "codigo_cvm":         r.get("Codigo_CVM"),
            "data_referencia":    r["Data_Referencia"].isoformat() if pd.notna(r["Data_Referencia"]) else None,
            "data_entrega":       r["Data_Entrega"].isoformat()    if pd.notna(r["Data_Entrega"])    else None,
            "categoria":          r.get("Categoria"),
            "tipo":               r.get("Tipo"),
            "especie":            r.get("Especie"),
            "assunto":            r.get("Assunto"),
            "tipo_apresentacao":  r.get("Tipo_Apresentacao"),
            "versao":             int(r["Versao"]),
            "link_download":      r.get("Link_Download"),
        })
    return rows

def upsert_batch(sb, rows: list[dict]):
    # sanitize antes do dedup: NaN → None para que o filtro abaixo os exclua
    rows = _sanitize(rows)
    # drop rows without a protocolo (NOT NULL PK) and deduplicate
    seen: dict = {}
    for row in rows:
        if row.get("protocolo_entrega"):
            seen[row["protocolo_entrega"]] = row
    rows = list(seen.values())
    if not rows:
        print("  0 docs (todos sem protocolo)")
        return
    upsert(sb, "ipe_docs", rows, "protocolo_entrega")
    print(f"  Upserted {len(rows)} docs")

def main():
    sb     = get_supabase()
    cnpjs  = watchlist_cnpjs()
    anos   = range(2021, date.today().year + 1)

    for ano in anos:
        try:
            df   = download_year(ano)
            rows = process(df, cnpjs)
            upsert_batch(sb, rows)
            print(f"  {ano}: {len(rows)} docs da watchlist")
        except Exception as e:
            print(f"  ERRO {ano}: {e}")

if __name__ == "__main__":
    main()
