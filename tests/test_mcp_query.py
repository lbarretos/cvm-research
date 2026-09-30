"""
MCP cvm-research (scripts/mcp/cvm_mcp.py): a ferramenta query().

O banco abre em mode=ro, então o filtro de palavras não precisa (nem deve) barrar SELECTs
válidos: replace() como função, 'update' dentro de um MATCH do FTS, LIKE '%create%'. A guarda
de verdade é o authorizer do SQLite. Além disso, células gigantes (texto_extraido chega a
12 milhões de caracteres) voltam cortadas e consultas lentas são abortadas.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "mcp"))

import cvm_mcp  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "cvm.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE ipe_docs (protocolo_entrega TEXT PRIMARY KEY, assunto TEXT, texto_extraido TEXT);
        CREATE VIRTUAL TABLE ipe_docs_fts USING fts5(protocolo_entrega UNINDEXED, texto_extraido);
    """)
    conn.executemany("INSERT INTO ipe_docs VALUES (?, ?, ?)", [
        ("P1", "Ata para create de comitê", "Fato relevante: update do guidance de capex."),
        ("P2", "Documento longo", "x" * 200_000),
    ])
    conn.execute("INSERT INTO ipe_docs_fts SELECT protocolo_entrega, texto_extraido FROM ipe_docs")
    conn.commit()
    conn.close()
    monkeypatch.setattr(cvm_mcp, "DB_PATH", path)
    return path


def test_funcao_replace_e_permitida(db):
    r = cvm_mcp.query("SELECT replace(texto_extraido, 'update', 'revisão') AS t FROM ipe_docs WHERE protocolo_entrega = 'P1'")
    assert r == [{"t": "Fato relevante: revisão do guidance de capex."}]


def test_palavra_proibida_dentro_de_literal_e_permitida(db):
    assert cvm_mcp.query("SELECT protocolo_entrega FROM ipe_docs WHERE assunto LIKE '%create%'") == [
        {"protocolo_entrega": "P1"}]
    r = cvm_mcp.query("SELECT protocolo_entrega, snippet(ipe_docs_fts, -1, '[', ']', '…', 5) AS s "
                      "FROM ipe_docs_fts WHERE ipe_docs_fts MATCH 'update'")
    assert r[0]["protocolo_entrega"] == "P1" and "[update]" in r[0]["s"]


@pytest.mark.parametrize("sql", [
    "INSERT INTO ipe_docs VALUES ('P3', 'a', 'b')",
    "WITH x AS (SELECT 1) INSERT INTO ipe_docs VALUES ('P3', 'a', 'b')",
    "SELECT 1; DELETE FROM ipe_docs",
    "SELECT 1 FROM ipe_docs WHERE 0 UNION SELECT 1 FROM ipe_docs /* */ ; REPLACE INTO ipe_docs VALUES ('P1','a','b')",
])
def test_escrita_e_recusada(db, sql):
    with pytest.raises(ValueError):
        cvm_mcp.query(sql)


def test_authorizer_nega_o_que_passa_pelo_filtro(db):
    """pragma_* como função não tem a palavra PRAGMA solta, mas o authorizer barra."""
    with pytest.raises(ValueError, match="não permitida"):
        cvm_mcp.query("SELECT * FROM pragma_table_info('ipe_docs')")


def test_celula_grande_e_truncada(db):
    [r] = cvm_mcp.query("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega = 'P2'")
    t = r["texto_extraido"]
    assert t.startswith("x" * cvm_mcp.MAX_CELL_CHARS)
    assert t[cvm_mcp.MAX_CELL_CHARS:].startswith("…[truncado: 200000 chars; use substr(")
    [r] = cvm_mcp.query("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega = 'P1'")
    assert r["texto_extraido"] == "Fato relevante: update do guidance de capex."


def test_timeout_aborta_consulta_lenta(db, monkeypatch):
    monkeypatch.setattr(cvm_mcp, "QUERY_TIMEOUT_S", 0.3)
    with pytest.raises(ValueError, match="abortada"):
        cvm_mcp.query("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                      "SELECT max(i) FROM n")
