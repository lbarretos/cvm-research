"""
Baixa os CSVs anuais do IPE e faz upsert dos metadados no Supabase.
Não baixa nem armazena PDFs — apenas metadados + link_download.
"""
import io
import zipfile
from datetime import date
import httpx
import pandas as pd
from utils import get_supabase, watchlist_cnpjs

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
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
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

def _sanitize(rows: list[dict]) -> list[dict]:
    def clean(val):
        if isinstance(val, float) and val != val:
            return None
        return val
    return [{k: clean(v) for k, v in row.items()} for row in rows]

def upsert_batch(sb, rows: list[dict], batch=500):
    rows = _sanitize(rows)
    for i in range(0, len(rows), batch):
        sb.table("ipe_docs").upsert(
            rows[i:i+batch],
            on_conflict="protocolo_entrega",
        ).execute()
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
