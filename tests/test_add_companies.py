"""
Testes para scripts/ingest/add_companies.py.
"""
import os
import sys
from pathlib import Path
import csv
import pandas as pd
import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "scripts", "ingest"))

from add_companies import (
    normalize_cnpj,
    map_setor,
    to_watchlist_rows,
    append_to_watchlist,
)


def test_normalize_cnpj():
    assert normalize_cnpj("00080671000100") == "00.080.671/0001-00"
    assert normalize_cnpj("00.080.671/0001-00") == "00.080.671/0001-00"
    assert normalize_cnpj("123") == "123"


def test_map_setor():
    assert map_setor("Alimentos") == "Agro"
    assert map_setor("Serviços Transporte e Logística") == "Mobilidade"
    assert map_setor("Educação") == "Educacao"
    assert map_setor("Setor Inexistente") == "Outros"


def test_to_watchlist_rows():
    df = pd.DataFrame([
        {
            "ticker": "CRMU",
            "cnpj": "00.080.671/0001-00",
            "codigo_cvm": "26190",
            "nome_cvm": "CARAMURU ALIMENTOS S.A.",
            "nome_b3": "",
            "setor_cvm": "Alimentos",
            "ticker_confidence": "assumed",
        }
    ])
    rows = to_watchlist_rows(df)
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "CRMU"
    assert r["cnpj"] == "00.080.671/0001-00"
    assert r["codigo_cvm"] == "26190"
    assert r["nome_cvm"] == "CARAMURU ALIMENTOS S.A."
    assert r["setor"] == "Agro"
    assert r["status_cvm"] == "ATIVO"
    assert r["observacao"] == "auto:assumed"


def test_append_to_watchlist_preserves_headers(tmp_path):
    target = tmp_path / "watchlist_test.csv"
    with open(target, "w", encoding="utf-8") as f:
        f.write("ticker,cnpj,codigo_cvm,nome_cvm,setor,status_cvm,observacao\n")
        f.write("TEST3,11.222.333/0001-44,12345,TEST SA,Outros,ATIVO,\n")

    new_rows = [{
        "ticker": "VLIM",
        "cnpj": "42.276.907/0001-28",
        "codigo_cvm": "28045",
        "nome_cvm": "VLI MULTIMODAL S.A",
        "setor": "Mobilidade",
        "status_cvm": "ATIVO",
        "observacao": "manual: Categoria B",
    }]

    import add_companies as ac
    original_path = ac.WATCHLIST_PATH
    try:
        ac.WATCHLIST_PATH = target
        append_to_watchlist(new_rows)
    finally:
        ac.WATCHLIST_PATH = original_path

    with open(target, encoding="utf-8") as f:
        lines = [r for r in csv.DictReader(f)]
    assert len(lines) == 2
    assert lines[1]["ticker"] == "VLIM"
    assert lines[1]["cnpj"] == "42.276.907/0001-28"
    assert lines[1]["observacao"] == "manual: Categoria B"
