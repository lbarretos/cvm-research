"""
Ingere os demonstrativos financeiros anuais (DFP) da CVM no Supabase.

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip
Tipos ingeridos (consolidado): BPA, BPP, DRE, DFC_MI, DVA
Tabela destino: demonstrativos_contabeis (fonte='DFP')
Cobertura: 2021-atual, somente empresas da watchlist

Normalização de escala:
  ESCALA_MOEDA = 'MIL'      → vl_conta = VL_CONTA × 1000
  ESCALA_MOEDA = 'UNIDADE'  → vl_conta = VL_CONTA × 1
  VL_CONTA vazio/NaN        → vl_conta = NULL (contas estruturais sem valor)
  ESCALA_MOEDA desconhecida → ValueError (falha ruidosa — parar o processamento)
"""
from datetime import date

import pandas as pd

from utils import _date, _float, _int, _sanitize, download_year, get_supabase, upsert, watchlist_cnpjs

FONTE = "DFP"
TIPOS = ["BPA", "BPP", "DRE", "DFC_MI", "DVA"]
SCALE = {"MIL": 1000, "UNIDADE": 1}
CONFLICT = "cnpj_companhia,fonte,tipo_doc,data_referencia,versao,cd_conta,ordem_exercicio"

# CVM grava ORDEM_EXERC em caixa alta; normaliza para o valor do CHECK constraint
ORDEM_MAP = {"ÚLTIMO": "Último", "PENÚLTIMO": "Penúltimo"}


def process_df(df: pd.DataFrame, cnpjs: set, tipo_doc: str) -> list[dict]:
    """
    Processa um DataFrame de um tipo de demonstrativo e retorna linhas para upsert.

    Fluxo:
      CSV (dtype=str) → filtrar watchlist → normalizar escala → list[dict]

    Campos CVM mapeados (nomes reais no CSV):
      CNPJ_CIA, DT_REFER, VERSAO, ORDEM_EXERC,
      DT_FIM_EXERC, CD_CONTA, DS_CONTA,
      VL_CONTA, ESCALA_MOEDA
    Nota: DFP não tem DT_INI_EXERC — armazenado como NULL.
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
            "dt_ini_exerc":    None,  # DFP não publica DT_INI_EXERC
            "dt_fim_exerc":    _date(r.get("DT_FIM_EXERC")),
            "cd_conta":        r.get("CD_CONTA"),
            "ds_conta":        r.get("DS_CONTA"),
            "vl_conta":        vl,
        })
    return rows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--historico", action="store_true",
                        help="Reprocessa todos os anos desde --desde até hoje")
    parser.add_argument("--desde", type=int, default=2021, metavar="ANO",
                        help="Ano inicial para --historico (padrão: 2021)")
    args = parser.parse_args()

    hoje = date.today()
    if args.historico:
        # Revisão completa: 2021 até ano corrente
        anos = range(args.desde, hoje.year + 1)
        print(f"Modo histórico: processando {args.desde} → {hoje.year}")
    else:
        # Semanal: ano anterior (DFP divulgado até abril do ano corrente)
        # + ano corrente (fallback: se existir ZIP antecipado, captura; 404 é silencioso)
        anos = [hoje.year - 1, hoje.year]
        print(f"Modo semanal: processando {hoje.year - 1} e {hoje.year}")

    sb    = get_supabase()
    cnpjs = watchlist_cnpjs()

    for ano in anos:
        print(f"\n── DFP {ano} ──")
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
