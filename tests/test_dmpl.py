"""DMPL (scripts/ingest/dmpl.py): CSV da CVM (matriz conta × COLUNA_DF) → tabela dmpl."""
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

import dmpl  # noqa: E402

WEG = "84.429.695/0001-11"


def _csv(linhas, cnpj=WEG, escala="MIL", ordem="ÚLTIMO"):
    """linhas = [(cd, ds, coluna_df, valor)] no layout do dfp_cia_aberta_DMPL_con_<ano>.csv (conferido em 2026-10-30)."""
    return pd.DataFrame([{"CNPJ_CIA": cnpj, "DT_REFER": "2024-12-31", "VERSAO": "1", "DENOM_CIA": "WEG S.A.",
                          "CD_CVM": "5410", "GRUPO_DFP": "DF Consolidado", "MOEDA": "REAL", "ESCALA_MOEDA": escala,
                          "ORDEM_EXERC": ordem, "DT_INI_EXERC": "2024-01-01", "DT_FIM_EXERC": "2024-12-31",
                          "COLUNA_DF": col, "CD_CONTA": cd, "DS_CONTA": ds, "VL_CONTA": vl, "ST_CONTA_FIXA": "S"}
                         for cd, ds, col, vl in linhas], dtype=str)


def test_colunas_do_plano_padrao_viram_codigo_curto():
    assert dmpl.coluna("Reservas de Capital, Opções Outorgadas e Ações em Tesouraria") == "reservas_capital"
    assert dmpl.coluna("Patrimônio Líquido Consolidado") == "pl_consolidado"
    assert dmpl.coluna("Participação dos Não Controladores") == "nao_controladores"
    assert dmpl.coluna("Reservas de Lucros a Realizar") == "reservas_de_lucros_a_realizar"   # fora do padrão: guarda
    assert dmpl.coluna(float("nan")) is None and dmpl.coluna("") is None


def test_process_escala_filtra_watchlist_e_descarta_sem_coluna():
    df = pd.concat([_csv([("5.04.06", "Dividendos", "Patrimônio Líquido Consolidado", "-786877.0000000000"),
                          ("5.04.07", "Juros sobre Capital Próprio", "Patrimônio Líquido Consolidado", "-1134258"),
                          ("5.04.06", "Dividendos", None, "-1")]),
                    _csv([("5.04.06", "Dividendos", "Patrimônio Líquido Consolidado", "-5")], cnpj="00.000.000/0001-91")])
    rows = dmpl.process(df, {WEG}, "DFP")
    assert [(r["cd_conta"], r["coluna"], r["vl_conta"], r["ordem_exercicio"]) for r in rows] == [
        ("5.04.06", "pl_consolidado", -786_877_000.0, "Último"),
        ("5.04.07", "pl_consolidado", -1_134_258_000.0, "Último")]


def test_escala_desconhecida_falha():
    with pytest.raises(ValueError):
        dmpl.process(_csv([("5.07", "Saldos Finais", "Patrimônio Líquido", "1")], escala="MILHAO"), {WEG}, "DFP")


def test_gravar_cria_a_tabela_e_e_idempotente():
    conn = sqlite3.connect(":memory:")
    rows = dmpl.process(_csv([("5.07", "Saldos Finais", "Patrimônio Líquido Consolidado", "23125217")]), {WEG}, "DFP")
    assert dmpl.gravar(conn, rows) == 1 and dmpl.gravar(conn, rows) == 1
    assert conn.execute("SELECT COUNT(*), MAX(vl_conta) FROM dmpl").fetchone() == (1, 23_125_217_000.0)
