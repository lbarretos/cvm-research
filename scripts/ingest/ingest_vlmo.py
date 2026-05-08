"""Baixa VLMO (posição consolidada + movimentações) e faz upsert no Supabase."""
import io
import zipfile
from datetime import date
import httpx
import pandas as pd
from utils import get_supabase, watchlist_cnpjs

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS"

def download_year(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    url = f"{BASE_URL}/vlmo_cia_aberta_{year}.zip"
    print(f"Baixando {url}...")
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    posicao = movimentacoes = None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            with z.open(name) as f:
                df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
            if "_con_" in name:
                movimentacoes = df
            else:
                posicao = df
    return posicao, movimentacoes

def process_posicao(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)].copy()
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "protocolo_entrega":    r.get("Protocolo_Entrega"),
            "cnpj_companhia":       r["CNPJ_Companhia"],
            "nome_companhia":       r.get("Nome_Companhia"),
            "data_referencia":      r.get("Data_Referencia"),
            "versao":               _int(r.get("Versao")),
            "codigo_cvm":           r.get("Codigo_CVM"),
            "categoria":            r.get("Categoria"),
            "tipo":                 r.get("Tipo"),
            "data_entrega":         r.get("Data_Entrega"),
            "tipo_apresentacao":    r.get("Tipo_Apresentacao"),
            "motivo_reapresentacao":r.get("Motivo_Reapresentacao"),
            "link_download":        r.get("Link_Download"),
        })
    return rows

def process_movimentacoes(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)].copy()
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "cnpj_companhia":         r["CNPJ_Companhia"],
            "nome_companhia":         r.get("Nome_Companhia"),
            "data_referencia":        r.get("Data_Referencia"),
            "versao":                 _int(r.get("Versao")),
            "tipo_empresa":           r.get("Tipo_Empresa"),
            "empresa":                r.get("Empresa"),
            "tipo_cargo":             r.get("Tipo_Cargo"),
            "tipo_movimentacao":      r.get("Tipo_Movimentacao"),
            "descricao_movimentacao": r.get("Descricao_Movimentacao"),
            "tipo_operacao":          r.get("Tipo_Operacao"),
            "tipo_ativo":             r.get("Tipo_Ativo"),
            "caracteristica":         r.get("Caracteristica_Valor_Mobiliario"),
            "intermediario":          r.get("Intermediario"),
            "data_movimentacao":      r.get("Data_Movimentacao") or None,
            "quantidade":             _int(r.get("Quantidade")),
            "preco_unitario":         _float(r.get("Preco_Unitario")),
            "volume":                 _float(r.get("Volume")),
        })
    return rows

def _int(v):
    try: return int(float(str(v).replace(",", ".")))
    except: return None

def _float(v):
    try: return float(str(v).replace(",", "."))
    except: return None

def upsert_batch(sb, table, rows, batch=500):
    for i in range(0, len(rows), batch):
        sb.table(table).upsert(rows[i:i+batch]).execute()
    print(f"  {table}: {len(rows)} rows")

def main():
    sb    = get_supabase()
    cnpjs = watchlist_cnpjs()

    for ano in range(2021, date.today().year + 1):
        try:
            posicao, movs = download_year(ano)
            if posicao is not None:
                upsert_batch(sb, "vlmo_posicao", process_posicao(posicao, cnpjs))
            if movs is not None:
                upsert_batch(sb, "vlmo_movimentacoes", process_movimentacoes(movs, cnpjs))
        except Exception as e:
            print(f"  ERRO {ano}: {e}")

if __name__ == "__main__":
    main()
