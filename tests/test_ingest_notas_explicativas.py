"""
Testes do ingestor de Notas Explicativas (ITR/DFP).

Cobre:
  - latest_por_periodo: reduz o CSV de metadados a 1 linha por (cnpj, período),
    escolhendo sempre a maior VERSAO.
  - extrair_pdf_do_pacote: acha o PDF dentro do ZIP do pacote do documento.
  - Operações SQLite: _upsert_pendente_rows, _fetch_pendentes, _salvar.
  - fetch_notas_texto: download + extração de texto, com rede e pdfplumber mockados.
"""
import io
import sqlite3
import sys
import os
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from ingest_notas_explicativas import (
    latest_por_periodo,
    extrair_pdf_do_pacote,
    fetch_notas_texto,
    _upsert_pendente_rows,
    _fetch_pendentes,
    _salvar,
)


# ── latest_por_periodo ────────────────────────────────────────────────────────

def test_latest_por_periodo_escolhe_maior_versao():
    df = pd.DataFrame([
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "156716"},
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "2", "ID_DOC": "156792"},
    ])
    result = latest_por_periodo(df, {"88.610.126/0001-29"}, fonte="ITR")

    assert result == [{
        "cnpj_companhia": "88.610.126/0001-29",
        "fonte": "ITR",
        "data_referencia": "2026-03-31",
        "versao": 2,
        "numero_sequencial_documento": 156792,
    }]


def test_latest_por_periodo_filtra_por_watchlist():
    df = pd.DataFrame([
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "156792"},
        {"CNPJ_CIA": "00.000.000/0001-91", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "999"},
    ])
    result = latest_por_periodo(df, {"88.610.126/0001-29"}, fonte="ITR")

    assert len(result) == 1
    assert result[0]["cnpj_companhia"] == "88.610.126/0001-29"


def test_latest_por_periodo_multiplos_periodos_mesma_empresa():
    df = pd.DataFrame([
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2025-12-31", "VERSAO": "1", "ID_DOC": "111"},
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "222"},
    ])
    result = latest_por_periodo(df, {"88.610.126/0001-29"}, fonte="ITR")

    assert len(result) == 2
    periodos = {r["data_referencia"] for r in result}
    assert periodos == {"2025-12-31", "2026-03-31"}


# ── extrair_pdf_do_pacote ─────────────────────────────────────────────────────

def test_extrair_pdf_do_pacote_encontra_pdf():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("006211ITR31-03-2026v2.xml", b"<xml/>")
        z.writestr("156792_006211_ts.pdf", b"%PDF-1.4 conteudo fake")
        z.writestr("DadosDocumento.xlsx", b"fake xlsx")

    pdf_bytes = extrair_pdf_do_pacote(buf.getvalue())

    assert pdf_bytes == b"%PDF-1.4 conteudo fake"


def test_extrair_pdf_do_pacote_sem_pdf_retorna_none():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apenas.xml", b"<xml/>")

    assert extrair_pdf_do_pacote(buf.getvalue()) is None
