"""Baixa VLMO (posição consolidada + movimentações) e faz upsert no banco local."""
import io
import zipfile
from datetime import date
import pandas as pd
from utils import get_db, watchlist_cnpjs, _http_get, _int, _float, upsert

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS"

# Colunas que compõem a chave única de movimentações (vlmo_mov_uniq).
# O CSV da CVM contém linhas duplicadas sob essa chave — deduplica-se antes do upsert.
_MOV_KEY_COLS = [
    "CNPJ_Companhia", "Data_Referencia", "Versao", "Empresa",
    "Tipo_Cargo", "Tipo_Movimentacao", "Tipo_Ativo",
    "Caracteristica_Valor_Mobiliario", "Data_Movimentacao", "Quantidade",
]

def download_year(year: int) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    url = f"{BASE_URL}/vlmo_cia_aberta_{year}.zip"
    print(f"Baixando {url}...")
    r = _http_get(url, timeout=120)
    posicao = movimentacoes = None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if not name.endswith(".csv") or ".." in name or name.startswith("/"):
                continue
            with z.open(name) as f:
                df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
            if "_con_" in name:
                # CVM publica linhas duplicadas sob vlmo_mov_uniq — remove antes de processar
                before = len(df)
                df = df.drop_duplicates(subset=_MOV_KEY_COLS)
                dropped = before - len(df)
                if dropped:
                    print(f"  {name}: {dropped} duplicatas removidas do CSV")
                movimentacoes = df
            else:
                posicao = df
    return posicao, movimentacoes

def process_posicao(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)].copy()
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "protocolo_entrega":     r.get("Protocolo_Entrega"),
            "cnpj_companhia":        r["CNPJ_Companhia"],
            "nome_companhia":        r.get("Nome_Companhia"),
            "data_referencia":       r.get("Data_Referencia"),
            "versao":                _int(r.get("Versao")),
            "codigo_cvm":            r.get("Codigo_CVM"),
            "categoria":             r.get("Categoria"),
            "tipo":                  r.get("Tipo"),
            "data_entrega":          r.get("Data_Entrega"),
            "tipo_apresentacao":     r.get("Tipo_Apresentacao"),
            "motivo_reapresentacao": r.get("Motivo_Reapresentacao"),
            "link_download":         r.get("Link_Download"),
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

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--desde", type=int, default=2021, metavar="ANO",
                        help="Ano inicial (padrão: 2021)")
    args = parser.parse_args()

    conn  = get_db()
    cnpjs = watchlist_cnpjs()

    for ano in range(args.desde, date.today().year + 1):
        posicao, movs = download_year(ano)
        if posicao is not None:
            upsert(conn, "vlmo_posicao", process_posicao(posicao, cnpjs),
                   conflict="protocolo_entrega")
        if movs is not None:
            upsert(conn, "vlmo_movimentacoes", process_movimentacoes(movs, cnpjs),
                   conflict="vlmo_mov_uniq")

if __name__ == "__main__":
    main()
