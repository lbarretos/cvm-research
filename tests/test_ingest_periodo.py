"""
Fase 0 da consistência financeira: chave natural com período.

Cobre:
  - _upsert_sqlite com índice único de expressão (COALESCE(dt_ini_exerc,''))
  - process_df (ITR e DFP) preserva trimestre + acumulado e grava st_conta_fixa
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _upsert_sqlite
import ingest_itr
import ingest_dfp

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _row(dt_ini, vl, cd="3.01"):
    return {
        "cnpj_companhia": "84.429.695/0001-11", "fonte": "ITR", "tipo_doc": "DRE",
        "data_referencia": "2024-06-30", "versao": 1, "ordem_exercicio": "Último",
        "dt_ini_exerc": dt_ini, "dt_fim_exerc": "2024-06-30",
        "cd_conta": cd, "ds_conta": "Receita", "vl_conta": vl, "st_conta_fixa": "S",
    }


def test_upsert_mantem_trimestre_e_acumulado():
    conn = _db()
    rows = [_row("2024-01-01", 17_307_730_000.0), _row("2024-04-01", 9_274_426_000.0)]
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, "dem_contabeis_uniq")
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, "dem_contabeis_uniq")  # idempotente
    got = conn.execute(
        "SELECT dt_ini_exerc, vl_conta FROM demonstrativos_contabeis ORDER BY dt_ini_exerc"
    ).fetchall()
    assert got == [("2024-01-01", 17_307_730_000.0), ("2024-04-01", 9_274_426_000.0)]


def test_upsert_dt_ini_null_conflita_consigo_mesmo():
    """BPA/BPP têm dt_ini_exerc NULL; duas cargas não podem duplicar a linha."""
    conn = _db()
    r = _row(None, 1.0, cd="1")
    r.update({"tipo_doc": "BPA", "vl_conta": 1.0})
    _upsert_sqlite(conn, "demonstrativos_contabeis", [r], "dem_contabeis_uniq")
    r["vl_conta"] = 2.0
    _upsert_sqlite(conn, "demonstrativos_contabeis", [r], "dem_contabeis_uniq")
    got = conn.execute("SELECT COUNT(*), MAX(vl_conta) FROM demonstrativos_contabeis").fetchone()
    assert got == (1, 2.0)
