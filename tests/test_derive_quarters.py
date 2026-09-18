"""
Fase 5 da consistência financeira: Camada 6 (desacúmulo) + demonstrativos_trimestrais.
"""
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import derive_quarters as dq

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def test_schema_trimestrais():
    conn = _db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(demonstrativos_trimestrais)")]
    assert {"run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
            "cd_conta", "ds_conta", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
            "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"} <= set(cols)
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('r', 6, 'derive_quarters')")
    sql = ("INSERT INTO demonstrativos_trimestrais (run_id, cnpj_companhia, tipo_doc, safra, exercicio_ini, dt_ini_exerc, "
           "dt_fim_exerc, trimestre, cd_conta, origem, flag) VALUES ('r', ?, 'DRE', 'original', '2024-01-01', ?, ?, ?, '3.01', 'derivado', ?)")
    conn.execute(sql, (CNPJ, "2024-10-01", "2024-12-31", 4, "linha_sem_par"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2024-10-01", "2024-12-31", 4, None))          # UNIQUE (cnpj, tipo, safra, fim, conta)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2025-01-01", "2025-03-31", 5, None))          # trimestre 1..4
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2025-01-01", "2025-03-31", 1, "inventada"))   # CHECK flag


def test_calendario():
    assert dq.meses("2024-01-01", "2024-03-31") == 3 and dq.meses("2024-01-01", "2024-12-31") == 12
    assert dq.meses("2023-04-01", "2024-03-31") == 12 and dq.meses("2024-01-01", "2024-01-31") == 1
    assert dq.trimestre_de("2024-01-01", "2024-06-30") == 2 and dq.trimestre_de("2023-04-01", "2023-06-30") == 1
    assert dq.trimestre_de("2024-01-01", "2024-01-31") is None and dq.trimestre_de("2023-01-01", "2024-01-31") is None
    assert dq.inicio_trimestre("2024-01-01", 1) == "2024-01-01" and dq.inicio_trimestre("2024-01-01", 4) == "2024-10-01"
    assert dq.inicio_trimestre("2023-04-01", 4) == "2024-01-01"
