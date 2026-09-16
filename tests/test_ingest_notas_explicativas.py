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


@patch("ingest_notas_explicativas.pdfplumber.open")
@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_sucesso(mock_http_get, mock_pdf_open):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("156792_006211_ts.pdf", b"%PDF-1.4 fake")
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    page = MagicMock()
    page.extract_text.return_value = "Despesa de depreciação do período (26.581)"
    mock_pdf_open.return_value.__enter__.return_value.pages = [page]

    texto = fetch_notas_texto(156792)

    assert texto == "Despesa de depreciação do período (26.581)"
    mock_http_get.assert_called_once_with(
        "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
        "?CodigoInstituicao=1&NumeroSequencialDocumento=156792",
        timeout=120,
    )


@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_sem_pdf_no_zip_retorna_none(mock_http_get):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apenas.xml", b"<xml/>")
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    assert fetch_notas_texto(999) is None


@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_erro_rede_retorna_none(mock_http_get):
    """Qualquer exceção (rede, ZIP corrompido, etc.) deve virar None, não crash."""
    mock_http_get.side_effect = Exception("timeout")

    assert fetch_notas_texto(156792) is None


@patch("ingest_notas_explicativas.pdfplumber.open")
@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_remove_nul_bytes(mock_http_get, mock_pdf_open):
    """SQLite rejeita strings com NUL — mesma proteção de extract_pdf.py."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.pdf", b"%PDF-1.4")
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    page = MagicMock()
    page.extract_text.return_value = "texto\x00com\x00nul"
    mock_pdf_open.return_value.__enter__.return_value.pages = [page]

    texto = fetch_notas_texto(1)

    assert "\x00" not in texto
    assert texto == "textocomnul"


def _make_notas_conn():
    """In-memory SQLite com o schema mínimo de notas_explicativas (ver schema.sql)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE notas_explicativas (
            id                           INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj_companhia               TEXT NOT NULL,
            fonte                        TEXT NOT NULL CHECK (fonte IN ('ITR','DFP')),
            data_referencia              TEXT NOT NULL,
            versao                       INTEGER NOT NULL DEFAULT 1,
            numero_sequencial_documento  INTEGER NOT NULL,
            link_download                TEXT,
            texto_extraido               TEXT,
            extraido_em                  TEXT,
            extracao_falhou              INTEGER DEFAULT 0,
            chars_extraidos              INTEGER,
            created_at                   TEXT DEFAULT (datetime('now')),
            updated_at                   TEXT DEFAULT (datetime('now')),
            UNIQUE (cnpj_companhia, fonte, data_referencia)
        );
    """)
    return conn


def test_upsert_pendente_rows_insere_nova_linha():
    conn = _make_notas_conn()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    row = conn.execute(
        "SELECT versao, numero_sequencial_documento, texto_extraido FROM notas_explicativas"
    ).fetchone()
    assert row == (2, 156792, None)


def test_upsert_pendente_rows_versao_igual_preserva_texto():
    """Re-rodar o ingestor sem nova versão não deve apagar texto já extraído."""
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, versao, numero_sequencial_documento, texto_extraido) "
        "VALUES ('88.610.126/0001-29', 'ITR', '2026-03-31', 2, 156792, 'texto já extraído')"
    )
    conn.commit()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    texto = conn.execute("SELECT texto_extraido FROM notas_explicativas").fetchone()[0]
    assert texto == "texto já extraído"


def test_upsert_pendente_rows_versao_nova_reseta_texto():
    """Uma reapresentação (versão maior) invalida o texto extraído da versão antiga."""
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, versao, numero_sequencial_documento, "
        " texto_extraido, extracao_falhou) "
        "VALUES ('88.610.126/0001-29', 'ITR', '2026-03-31', 1, 156716, 'texto da v1', 1)"
    )
    conn.commit()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    row = conn.execute(
        "SELECT versao, numero_sequencial_documento, texto_extraido, extracao_falhou "
        "FROM notas_explicativas"
    ).fetchone()
    assert row == (2, 156792, None, 0)


def test_upsert_pendente_rows_popula_link_download():
    conn = _make_notas_conn()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    link = conn.execute("SELECT link_download FROM notas_explicativas").fetchone()[0]
    assert link == (
        "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
        "?CodigoInstituicao=1&NumeroSequencialDocumento=156792"
    )


def test_fetch_pendentes_filtra_texto_nulo_e_fonte_ano():
    conn = _make_notas_conn()
    conn.executemany(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, numero_sequencial_documento, texto_extraido) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("88.610.126/0001-29", "ITR", "2026-03-31", 1, None),           # pendente
            ("88.610.126/0001-29", "ITR", "2026-06-30", 2, "já extraído"),  # não pendente
            ("88.610.126/0001-29", "DFP", "2026-12-31", 3, None),           # fonte errada
            ("00.000.000/0001-00", "ITR", "2026-03-31", 4, None),           # cnpj fora do filtro
        ],
    )
    conn.commit()

    docs = _fetch_pendentes(
        conn, {"88.610.126/0001-29"}, fonte="ITR", ano=2026, limite=10
    )

    assert len(docs) == 1
    assert docs[0]["numero_sequencial_documento"] == 1


def test_fetch_pendentes_retry_failed_so_pega_falhas():
    conn = _make_notas_conn()
    conn.executemany(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, numero_sequencial_documento, "
        " texto_extraido, extracao_falhou) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("88.610.126/0001-29", "ITR", "2026-03-31", 1, None, 1),  # falhou antes
            ("88.610.126/0001-29", "ITR", "2026-06-30", 2, None, 0),  # nunca tentado
        ],
    )
    conn.commit()

    docs = _fetch_pendentes(
        conn, {"88.610.126/0001-29"}, fonte="ITR", ano=2026, limite=10, retry_failed=True
    )

    assert len(docs) == 1
    assert docs[0]["numero_sequencial_documento"] == 1


def test_salvar_sucesso_grava_texto_e_limpa_falha():
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(id, cnpj_companhia, fonte, data_referencia, numero_sequencial_documento, extracao_falhou) "
        "VALUES (1, '88.610.126/0001-29', 'ITR', '2026-03-31', 156792, 1)"
    )
    conn.commit()

    _salvar(conn, row_id=1, texto="texto extraído com sucesso")

    row = conn.execute(
        "SELECT texto_extraido, chars_extraidos, extracao_falhou FROM notas_explicativas WHERE id=1"
    ).fetchone()
    assert row == ("texto extraído com sucesso", len("texto extraído com sucesso"), 0)


def test_salvar_falha_marca_extracao_falhou():
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(id, cnpj_companhia, fonte, data_referencia, numero_sequencial_documento) "
        "VALUES (1, '88.610.126/0001-29', 'ITR', '2026-03-31', 156792)"
    )
    conn.commit()

    _salvar(conn, row_id=1, texto=None)

    row = conn.execute(
        "SELECT texto_extraido, extracao_falhou FROM notas_explicativas WHERE id=1"
    ).fetchone()
    assert row == (None, 1)


@patch("ingest_notas_explicativas.extrair_pdf_do_pacote")
@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_pacote_muito_grande_retorna_none(mock_http_get, mock_extrair_pdf):
    """
    O cap de tamanho deve barrar ANTES de tentar abrir o ZIP/PDF — não apenas
    coincidir com uma falha de parsing que aconteceria de qualquer forma.
    """
    resp = MagicMock()
    resp.content = b"x" * (151 * 1024 * 1024)  # 151MB > 150MB cap
    mock_http_get.return_value = resp

    assert fetch_notas_texto(1) is None
    mock_extrair_pdf.assert_not_called()
