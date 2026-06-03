"""
Ingere os demonstrativos financeiros trimestrais (ITR) da CVM no Supabase.

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip
Tipos ingeridos (consolidado): BPA, BPP, DRE, DFC_MI, DVA
Tabela destino: demonstrativos_contabeis (fonte='ITR')
Cobertura: 2021-atual, somente empresas da watchlist

O ZIP de cada ano é publicado progressivamente:
  - ITR 2026 já existe em maio/2026 (contém Q1)
  - Será atualizado com Q2, Q3 ao longo do ano
  - Cada run semanal baixa o ZIP do ano corrente novamente;
    o upsert ignora registros já existentes (idempotente via UNIQUE constraint)

Normalização: idêntica ao ingest_dfp.py (ver docstring lá).
"""
from datetime import date

import pandas as pd

from utils import _date, _float, _int, download_year, get_supabase, upsert, watchlist_cnpjs

FONTE = "ITR"
TIPOS = ["BPA", "BPP", "DRE", "DFC_MI", "DVA"]
SCALE = {"MIL": 1000, "UNIDADE": 1}
CONFLICT = "cnpj_companhia,fonte,tipo_doc,data_referencia,versao,cd_conta,ordem_exercicio"

# CVM grava ORDEM_EXERC em caixa alta; normaliza para o valor do CHECK constraint
ORDEM_MAP = {"ÚLTIMO": "Último", "PENÚLTIMO": "Penúltimo"}


def process_df(df: pd.DataFrame, cnpjs: set, tipo_doc: str) -> list[dict]:
    """
    Processa um DataFrame de um tipo de demonstrativo e retorna linhas para upsert.
    Ver ingest_dfp.process_df para detalhes do mapeamento de campos.

    Diferença DFP vs ITR: ITR publica DT_INI_EXERC (trimestre tem início definido).
    """
    df = df[df["CNPJ_CIA"].isin(cnpjs)]
    # CVM publica linhas genuinamente repetidas (mesmo valor) em alguns anos/tipos.
    # Deduplicamos apenas linhas 100% idênticas (chave + VL_CONTA).
    # Se a chave se repetir com VL_CONTA diferente, mantemos ambas → o upsert do
    # Postgres vai falhar com 21000, sinalizando um conflito real que precisa de
    # investigação em vez de ser silenciado.
    KEY_COLS = ["CNPJ_CIA", "DT_REFER", "VERSAO", "CD_CONTA", "ORDEM_EXERC"]
    df = df.drop_duplicates(subset=KEY_COLS + ["VL_CONTA"])
    rows = []
    for _, r in df.iterrows():
        escala = r.get("ESCALA_MOEDA", "")
        if escala not in SCALE:
            raise ValueError(f"Escala desconhecida: {escala!r} — CNPJ {r.get('CNPJ_CIA')} tipo {tipo_doc}")

        # VL_CONTA pode ser string vazia em contas estruturais (pai) → None, não crash
        vl_raw = _float(r.get("VL_CONTA"))
        vl = None if vl_raw is None else vl_raw * SCALE[escala]

        versao_raw = _int(r.get("VERSAO"))
        versao = versao_raw if versao_raw is not None else 1

        ordem_raw = (r.get("ORDEM_EXERC") or "").strip().upper()

        rows.append({
            "cnpj_companhia":  r.get("CNPJ_CIA"),
            "fonte":           FONTE,
            "tipo_doc":        tipo_doc,
            "data_referencia": _date(r.get("DT_REFER")),
            "versao":          versao,
            "ordem_exercicio": ORDEM_MAP.get(ordem_raw, ordem_raw),
            "dt_ini_exerc":    _date(r.get("DT_INI_EXERC")),
            "dt_fim_exerc":    _date(r.get("DT_FIM_EXERC")),
            "cd_conta":        r.get("CD_CONTA"),
            "ds_conta":        r.get("DS_CONTA"),
            "vl_conta":        vl,
        })
    return rows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--desde", type=int, default=None, metavar="ANO",
                        help="Ano inicial para processar múltiplos anos (ex: --desde 2016)")
    args = parser.parse_args()

    sb    = get_supabase()
    cnpjs = watchlist_cnpjs()
    hoje  = date.today()
    anos  = range(args.desde, hoje.year + 1) if args.desde else [hoje.year]
    if args.desde:
        print(f"Modo histórico: processando {args.desde} → {hoje.year}")

    for ano in anos:
        print(f"\n── ITR {ano} ──")
        try:
            dfs = download_year(ano, FONTE, TIPOS)
        except Exception as e:
            print(f"  ERRO download {ano}: {e}")
            continue

        for tipo in TIPOS:
            if tipo not in dfs:
                print(f"  {tipo}: não encontrado no ZIP")
                continue
            try:
                rows = process_df(dfs[tipo], cnpjs, tipo)
                if rows:
                    upsert(sb, "demonstrativos_contabeis", rows, CONFLICT)
                else:
                    print(f"  demonstrativos_contabeis [{tipo}]: 0 rows (watchlist sem dados)")
            except Exception as e:
                print(f"  ERRO {tipo}: {e}")


if __name__ == "__main__":
    main()
