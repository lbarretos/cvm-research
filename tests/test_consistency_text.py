"""
Fase 4 da consistência financeira: Camada 5 (trilha temporal) + Camada 4 (similaridade).
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def test_schema_timeline_unique_inclui_classificacao():
    conn = _db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cd_conta_ds_timeline)")]
    assert {"run_id", "cnpj_companhia", "tipo_doc", "cd_conta_pai", "ds_conta_norm", "fonte", "data_referencia",
            "cd_conta", "ds_conta", "st_conta_fixa", "data_referencia_anterior", "cd_conta_anterior",
            "ds_conta_anterior", "similarity_score", "classificacao"} <= set(cols)
    base = ("r", CNPJ, "DFC_MI", "6.01", "x", "DFP", "2023-12-31", "6.01.05", "X", "N")
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('r', 5, 'text_stability')")
    sql = ("INSERT INTO cd_conta_ds_timeline (run_id, cnpj_companhia, tipo_doc, cd_conta_pai, ds_conta_norm, fonte, "
           "data_referencia, cd_conta, ds_conta, st_conta_fixa, classificacao) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    conn.execute(sql, base + ("removida",))
    conn.execute(sql, base + ("nova",))            # mesmo código, classe diferente: permitido (cascata)
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, base + ("nova",))        # duplicata exata: não
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, base + ("inventada",))   # CHECK
