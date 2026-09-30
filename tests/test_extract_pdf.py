"""
Seleção dos documentos pendentes em extract_pdf._fetch_pendentes: categorias
prioritárias, filtro por tipo e ordem por data_entrega.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from extract_pdf import CATEGORIAS_PRIORITARIAS, _fetch_pendentes

CNPJ = "00.000.000/0001-00"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE ipe_docs (
            protocolo_entrega TEXT PRIMARY KEY, cnpj_companhia TEXT, data_entrega TEXT,
            categoria TEXT, tipo TEXT, assunto TEXT, link_download TEXT,
            texto_extraido TEXT, extracao_falhou INTEGER DEFAULT 0
        )
    """)
    docs = [
        # protocolo, cnpj, entrega, categoria, tipo, texto, falhou
        ("fr",    CNPJ, "2026-09-10", "Fato Relevante", None, None, 0),
        ("rca",   CNPJ, "2026-09-11", "Reunião da Administração", "Conselho de Administração", None, 0),
        ("pr",    CNPJ, "2026-09-12", "Dados Econômico-Financeiros", "Press-release", None, 0),
        ("dfi",   CNPJ, "2026-09-13", "Dados Econômico-Financeiros", "Demonstrações Financeiras Intermediárias", None, 0),
        ("rat",   CNPJ, "2026-09-14", "Dados Econômico-Financeiros", "Relatório de Agência de Rating", None, 0),
        ("outra", CNPJ, "2026-09-15", "Valores Mobiliários Negociados e Detidos", None, None, 0),
        ("feito", CNPJ, "2026-09-16", "Fato Relevante", None, "já extraído", 0),
        ("falha", CNPJ, "2026-09-17", "Fato Relevante", None, None, 1),
        ("alheio", "99.999.999/0001-99", "2026-09-18", "Fato Relevante", None, None, 0),
    ]
    c.executemany(
        "INSERT INTO ipe_docs (protocolo_entrega, cnpj_companhia, data_entrega, categoria, tipo,"
        " texto_extraido, extracao_falhou, assunto, link_download) VALUES (?,?,?,?,?,?,?,'a','http://x')",
        docs,
    )
    return c


def _protocolos(docs):
    return [d["protocolo_entrega"] for d in docs]


def test_prioritarias_incluem_rca_e_so_press_release(conn):
    docs = _fetch_pendentes(conn, {CNPJ}, CATEGORIAS_PRIORITARIAS, limite=50)
    # Mais recente primeiro; DFs e rating ficam de fora; RCA entra
    assert _protocolos(docs) == ["pr", "rca", "fr"]


def test_categoria_inexistente_resultado_saiu():
    assert "Resultado" not in CATEGORIAS_PRIORITARIAS
    assert CATEGORIAS_PRIORITARIAS["Dados Econômico-Financeiros"] == {"Press-release"}


def test_categoria_sem_filtro_de_tipo_traz_todos_os_tipos(conn):
    docs = _fetch_pendentes(conn, {CNPJ}, {"Dados Econômico-Financeiros": None}, limite=50)
    assert _protocolos(docs) == ["rat", "dfi", "pr"]


def test_retry_failed_so_traz_falhas(conn):
    docs = _fetch_pendentes(conn, {CNPJ}, CATEGORIAS_PRIORITARIAS, limite=50, retry_failed=True)
    assert _protocolos(docs) == ["falha"]


def test_limite_e_entradas_vazias(conn):
    assert _protocolos(_fetch_pendentes(conn, {CNPJ}, CATEGORIAS_PRIORITARIAS, limite=1)) == ["pr"]
    assert _fetch_pendentes(conn, set(), CATEGORIAS_PRIORITARIAS, limite=50) == []
    assert _fetch_pendentes(conn, {CNPJ}, {}, limite=50) == []
