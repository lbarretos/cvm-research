"""
MCP cvm-research (scripts/mcp/cvm_mcp.py): a ferramenta query().

O banco abre em mode=ro, então o filtro de palavras não precisa (nem deve) barrar SELECTs
válidos: replace() como função, 'update' dentro de um MATCH do FTS, LIKE '%create%'. A guarda
de verdade é o authorizer do SQLite. Além disso, células gigantes (texto_extraido chega a
12 milhões de caracteres) voltam cortadas e consultas lentas são abortadas.
"""
import json
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
    assert r["colunas"] == ["t"]
    assert r["linhas"] == [["Fato relevante: revisão do guidance de capex."]]


def test_palavra_proibida_dentro_de_literal_e_permitida(db):
    assert cvm_mcp.query("SELECT protocolo_entrega FROM ipe_docs WHERE assunto LIKE '%create%'") ["linhas"] == [
        ["P1"]]
    r = cvm_mcp.query("SELECT protocolo_entrega, snippet(ipe_docs_fts, -1, '[', ']', '…', 5) AS s "
                      "FROM ipe_docs_fts WHERE ipe_docs_fts MATCH 'update'")
    assert r["linhas"][0][0] == "P1" and "[update]" in r["linhas"][0][1]


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
    [[t]] = cvm_mcp.query("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega = 'P2'")["linhas"]
    assert t.startswith("x" * cvm_mcp.MAX_CELL_CHARS)
    assert t[cvm_mcp.MAX_CELL_CHARS:].startswith("…[truncado: 200000 chars; use substr(")
    [[t1]] = cvm_mcp.query("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega = 'P1'")["linhas"]
    assert t1 == "Fato relevante: update do guidance de capex."


def test_timeout_aborta_consulta_lenta(db, monkeypatch):
    monkeypatch.setattr(cvm_mcp, "QUERY_TIMEOUT_S", 0.3)
    with pytest.raises(ValueError, match="abortada"):
        cvm_mcp.query("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                      "SELECT max(i) FROM n")


def test_list_tables_nao_conta_views(db):
    """Contar uma view roda a consulta dela inteira (minutos em vw_balanco): rows vem null."""
    conn = sqlite3.connect(db)
    conn.execute("CREATE VIEW vw_assuntos AS SELECT assunto FROM ipe_docs")
    conn.commit()
    conn.close()
    por_nome = {l[0]: l for l in cvm_mcp.list_tables()["linhas"]}
    assert por_nome["ipe_docs"] == ["ipe_docs", "table", 2]
    assert por_nome["vw_assuntos"] == ["vw_assuntos", "view", None]


def test_describe_table_tem_prazo(db, monkeypatch):
    prazos = []
    original = cvm_mcp._com_prazo
    monkeypatch.setattr(cvm_mcp, "_com_prazo", lambda c: prazos.append(1) or original(c))
    assert [l[1] for l in cvm_mcp.describe_table("ipe_docs")["linhas"]] == ["protocolo_entrega", "assunto", "texto_extraido"]
    cvm_mcp.list_tables()
    assert len(prazos) == 2   # list_tables e describe_table, não só query(), param no prazo


def test_saida_e_tabular_sem_repetir_colunas(db):
    r = cvm_mcp.query("SELECT protocolo_entrega, assunto FROM ipe_docs ORDER BY 1")
    assert r == {"colunas": ["protocolo_entrega", "assunto"],
                 "linhas": [["P1", "Ata para create de comitê"], ["P2", "Documento longo"]]}


def test_orcamento_de_resposta_corta_linhas_e_avisa(db, monkeypatch):
    monkeypatch.setattr(cvm_mcp, "MAX_RESPONSE_CHARS", 1_000)
    r = cvm_mcp.query("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n LIMIT 300) "
                      "SELECT i, 'texto de enchimento' AS t FROM n")
    assert 0 < len(r["linhas"]) < 300
    assert "cortada" in r["aviso"] and "de 300 linhas" in r["aviso"]
    assert len(json.dumps(r, ensure_ascii=False)) < 1_300


def test_linha_unica_maior_que_o_orcamento_e_encurtada(db, monkeypatch):
    monkeypatch.setattr(cvm_mcp, "MAX_RESPONSE_CHARS", 2_000)
    r = cvm_mcp.query("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega = 'P2'")
    assert len(json.dumps(r)) < 3_000 and "truncado" in r["linhas"][0][0]


@pytest.fixture
def empresas(db):
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE companies (cnpj TEXT PRIMARY KEY, ticker TEXT, nome_cvm TEXT, setor TEXT);
        INSERT INTO companies VALUES
          ('33.000.167/0001-01', 'PETR4', 'PETROLEO BRASILEIRO S.A. PETROBRAS', 'Petróleo'),
          ('60.872.504/0001-23', 'ITUB4', 'ITAÚ UNIBANCO HOLDING S.A.', 'Financeiro'),
          ('61.532.644/0001-15', 'ITSA4', 'ITAÚSA S.A.', 'Financeiro');
    """)
    conn.commit()
    conn.close()


@pytest.mark.parametrize("texto, esperado", [
    ("PETR4", "PETR4"), ("petr4", "PETR4"), ("PETR3", "PETR4"), ("PETR", "PETR4"),
    ("33.000.167/0001-01", "PETR4"), ("33000167000101", "PETR4"), ("petrobras", "PETR4"),
    ("itau unibanco", "ITUB4"),
])
def test_resolve_company_acha(empresas, texto, esperado):
    r = cvm_mcp.resolve_company(texto)
    assert [c["ticker"] for c in r["candidatos"]] == [esperado]
    assert "aviso" not in r


def test_resolve_company_ambiguo_avisa(empresas):
    r = cvm_mcp.resolve_company("ita")
    assert {c["ticker"] for c in r["candidatos"]} == {"ITUB4", "ITSA4"}
    assert "mais de uma" in r["aviso"]


def test_resolve_company_fora_da_base_nao_devolve_vazio_mudo(empresas):
    r = cvm_mcp.resolve_company("MGLU3")
    assert r["candidatos"] == [] and "não está na base" in r["aviso"]
