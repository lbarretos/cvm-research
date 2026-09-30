"""
Lucro por ação (DRE 3.99) fica em R$/ação: a CVM publica o LPA sem a ESCALA_MOEDA
do documento. Antes, filing MIL gravava 8.540 para o LPA de 8,54 da Petrobras (DFP 2025).
"""
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

import ingest_dfp
import ingest_itr

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCHEMA = os.path.join(ROOT, "schema.sql")
MIGRATION = os.path.join(ROOT, "scripts", "migrations", "2026-09-30_lpa_escala.sql")
PETR = "33.000.167/0001-01"
VIVA = "33.839.910/0001-11"  # Vivara publica em UNIDADE


def _csv_dre(escala="MIL", dt_refer="2025-12-31", dt_ini="2025-01-01"):
    base = {"CNPJ_CIA": PETR, "DT_REFER": dt_refer, "VERSAO": "1", "ESCALA_MOEDA": escala,
            "ORDEM_EXERC": "ÚLTIMO", "DT_INI_EXERC": dt_ini, "DT_FIM_EXERC": dt_refer,
            "ST_CONTA_FIXA": "S"}
    return pd.DataFrame([
        {**base, "CD_CONTA": "3.01", "DS_CONTA": "Receita de Venda de Bens e/ou Serviços", "VL_CONTA": "490829000.0000000000"},
        {**base, "CD_CONTA": "3.99", "DS_CONTA": "Lucro por Ação - (Reais / Ação)", "VL_CONTA": ""},
        {**base, "CD_CONTA": "3.99.01.01", "DS_CONTA": "ON", "VL_CONTA": "8.5400000000"},
        {**base, "CD_CONTA": "3.99.02.02", "DS_CONTA": "PN", "VL_CONTA": "8.5400000000"},
    ])


def _vl(rows):
    return {r["cd_conta"]: r["vl_conta"] for r in rows}


@pytest.mark.parametrize("mod", [ingest_dfp, ingest_itr])
def test_process_df_nao_escala_lucro_por_acao(mod):
    vl = _vl(mod.process_df(_csv_dre(), {PETR}, "DRE"))
    assert vl["3.01"] == 490_829_000_000.0
    assert vl["3.99"] is None
    assert vl["3.99.01.01"] == 8.54
    assert vl["3.99.02.02"] == 8.54


def test_process_df_unidade_lpa_igual():
    vl = _vl(ingest_dfp.process_df(_csv_dre(escala="UNIDADE"), {PETR}, "DRE"))
    assert vl["3.01"] == 490_829_000.0
    assert vl["3.99.01.01"] == 8.54


def _run_sql(conn, path):
    with open(path, encoding="utf-8") as f:
        sql = "".join(l for l in f if not l.startswith("."))
    conn.executescript(sql)


def _ins(conn, cnpj, fonte, data_ref, cd, vl, tipo_doc="DRE"):
    conn.execute(
        "INSERT INTO demonstrativos_contabeis (cnpj_companhia, fonte, tipo_doc, data_referencia, versao,"
        " ordem_exercicio, dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta)"
        " VALUES (?, ?, ?, ?, 1, 'Último', '2025-01-01', ?, ?, 'x', ?)",
        (cnpj, fonte, tipo_doc, data_ref, data_ref, cd, vl))


def _get(conn, cnpj, fonte, cd):
    return conn.execute(
        "SELECT vl_conta FROM demonstrativos_contabeis WHERE cnpj_companhia=? AND fonte=? AND cd_conta=?",
        (cnpj, fonte, cd)).fetchone()[0]


def test_migracao_divide_so_lpa_de_filing_mil():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    _ins(conn, PETR, "DFP", "2025-12-31", "3.01", 490_829_000_000.0)
    _ins(conn, PETR, "DFP", "2025-12-31", "3.99.01.01", 8540.0)   # MIL, gravado ×1000
    _ins(conn, PETR, "DFP", "2025-12-31", "3.99", None)
    _ins(conn, VIVA, "DFP", "2024-12-31", "3.99.01.01", 2.77937)  # UNIDADE: já certo
    _ins(conn, VIVA, "DFP", "2024-12-31", "3.01", 2_000_000_000.0)

    _run_sql(conn, MIGRATION)

    assert _get(conn, PETR, "DFP", "3.99.01.01") == pytest.approx(8.54)
    assert _get(conn, PETR, "DFP", "3.01") == 490_829_000_000.0
    assert _get(conn, PETR, "DFP", "3.99") is None
    assert _get(conn, VIVA, "DFP", "3.99.01.01") == 2.77937
    assert _get(conn, VIVA, "DFP", "3.01") == 2_000_000_000.0

    # Segunda execução é recusada e não divide de novo
    with pytest.raises(sqlite3.IntegrityError):
        _run_sql(conn, MIGRATION)
    conn.rollback()
    assert _get(conn, PETR, "DFP", "3.99.01.01") == pytest.approx(8.54)
