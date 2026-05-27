"""
Baixa os ZIPs anuais do FRE e ingere as tabelas prioritárias no Supabase.
Um ZIP por ano contém ~30 CSVs; extrai só os necessários em memória.

Tabelas ingeridas:
  fre_capital_social       ← fre_cia_aberta_capital_social_{ano}.csv
  fre_posicao_acionaria    ← fre_cia_aberta_posicao_acionaria_{ano}.csv
  fre_remuneracao_orgao    ← fre_cia_aberta_remuneracao_maxima_minima_media_{ano}.csv
"""
import io
import zipfile
from datetime import date
import httpx
import pandas as pd
from utils import get_supabase, watchlist_cnpjs, _date, _int, _float, _sanitize, upsert

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS"

# Mapa: nome do CSV (sem ano e sem .csv) → função de processamento
TABELAS = {
    "capital_social":                   "process_capital_social",
    "posicao_acionaria":                "process_posicao_acionaria",
    "remuneracao_maxima_minima_media":  "process_remuneracao",
}

def download_year(year: int) -> dict[str, pd.DataFrame]:
    url = f"{BASE_URL}/fre_cia_aberta_{year}.zip"
    print(f"Baixando {url}...")
    r = httpx.get(url, timeout=180, follow_redirects=True)
    r.raise_for_status()
    dfs = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for suffix in TABELAS:
            fname = f"fre_cia_aberta_{suffix}_{year}.csv"
            if fname in z.namelist() and ".." not in fname and not fname.startswith("/"):
                with z.open(fname) as f:
                    dfs[suffix] = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return dfs

# ── processadores ────────────────────────────────────────────────────────────

def _base(r) -> dict:
    return {
        "cnpj_companhia": r.get("CNPJ_Companhia"),
        "nome_companhia": r.get("Nome_Companhia"),
        "data_referencia": _date(r.get("Data_Referencia")),
        "versao":          _int(r.get("Versao")),
        "id_documento":    _int(r.get("ID_Documento")),
    }

def process_capital_social(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)]
    rows = []
    for _, r in df.iterrows():
        rows.append({
            **_base(r),
            "id_capital_social":               _int(r.get("ID_Capital_Social")),
            "tipo_capital":                    r.get("Tipo_Capital"),
            "data_autorizacao_aprovacao":      _date(r.get("Data_Autorizacao_Aprovacao")),
            "valor_capital":                   _float(r.get("Valor_Capital")),
            "quantidade_acoes_ordinarias":     _int(r.get("Quantidade_Acoes_Ordinarias")),
            "quantidade_acoes_preferenciais":  _int(r.get("Quantidade_Acoes_Preferenciais")),
            "quantidade_total_acoes":          _int(r.get("Quantidade_Total_Acoes")),
        })
    return rows

def process_posicao_acionaria(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)]
    rows = []
    for _, r in df.iterrows():
        rows.append({
            **_base(r),
            "id_acionista":                               _int(r.get("ID_Acionista")),
            "acionista":                                  r.get("Acionista"),
            "tipo_pessoa_acionista":                      r.get("Tipo_Pessoa_Acionista"),
            "quantidade_acao_ordinaria_circulacao":       _int(r.get("Quantidade_Acao_Ordinaria_Circulacao")),
            "percentual_acao_ordinaria_circulacao":       _float(r.get("Percentual_Acao_Ordinaria_Circulacao")),
            "quantidade_acao_preferencial_circulacao":    _int(r.get("Quantidade_Acao_Preferencial_Circulacao")),
            "percentual_acao_preferencial_circulacao":    _float(r.get("Percentual_Acao_Preferencial_Circulacao")),
            "quantidade_total_acoes_circulacao":          _int(r.get("Quantidade_Total_Acoes_Circulacao")),
            "percentual_total_acoes_circulacao":          _float(r.get("Percentual_Total_Acoes_Circulacao")),
            "nacionalidade":                              r.get("Nacionalidade"),
            "residente_exterior":                         r.get("Residente_Exterior"),
            "acionista_controlador":                      r.get("Acionista_Controlador"),
            "participante_acordo_acionistas":             r.get("Participante_Acordo_Acionistas"),
            "data_composicao_capital_social":             _date(r.get("Data_Composicao_Capital_Social")),
        })
    return rows

def process_remuneracao(df: pd.DataFrame, cnpjs: set) -> list[dict]:
    df = df[df["CNPJ_Companhia"].isin(cnpjs)]
    rows = []
    for _, r in df.iterrows():
        rows.append({
            **_base(r),
            "data_inicio_exercicio":        _date(r.get("Data_Inicio_Exercicio_Social")),
            "data_fim_exercicio":           _date(r.get("Data_Fim_Exercicio_Social")),
            "orgao_administracao":          r.get("Orgao_Administracao"),
            "numero_membros":               _float(r.get("Numero_Membros")),
            "numero_membros_remunerados":   _float(r.get("Numero_Membros_Remunerados")),
            "valor_maior_remuneracao":      _float(r.get("Valor_Maior_Remuneracao")),
            "valor_menor_remuneracao":      _float(r.get("Valor_Menor_Remuneracao")),
            "valor_medio_remuneracao":      _float(r.get("Valor_Medio_Remuneracao")),
            "observacao":                   r.get("Observacao"),
        })
    return rows

# ── helpers e upsert ─────────────────────────────────────────────────────────
# _date, _int, _float, _sanitize, upsert importados de utils.py

# ── main ─────────────────────────────────────────────────────────────────────

PROCESSADORES = {
    "capital_social":                  ("fre_capital_social",     process_capital_social,    "cnpj_companhia,data_referencia,versao,id_capital_social"),
    "posicao_acionaria":               ("fre_posicao_acionaria",  process_posicao_acionaria, "cnpj_companhia,data_referencia,versao,id_acionista"),
    "remuneracao_maxima_minima_media": ("fre_remuneracao_orgao",  process_remuneracao,       "cnpj_companhia,data_referencia,versao,id_documento,orgao_administracao,data_fim_exercicio"),
}

def main():
    sb    = get_supabase()
    cnpjs = watchlist_cnpjs()

    for ano in range(2021, date.today().year + 1):
        print(f"\n── FRE {ano} ──")
        try:
            dfs = download_year(ano)
        except Exception as e:
            print(f"  ERRO download {ano}: {e}")
            continue

        for suffix, (table, fn, conflict) in PROCESSADORES.items():
            if suffix not in dfs:
                print(f"  {suffix}: não encontrado no ZIP")
                continue
            try:
                rows = fn(dfs[suffix], cnpjs)
                if rows:
                    upsert(sb, table, rows, conflict)
                else:
                    print(f"  {table}: 0 rows (watchlist sem dados)")
            except Exception as e:
                print(f"  ERRO {table}: {e}")

if __name__ == "__main__":
    main()
