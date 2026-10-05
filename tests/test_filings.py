"""
Etapa 1 (docs/proximos-passos/01-desempenho-e-operacao.md): a tabela `filings` e as views de
DRE/balanço que leem dela devolvem exatamente as linhas das views antigas (que recalculavam
MAX(versao) e o plano de contas sobre a base inteira). As definições antigas vêm da migração
2026-09-30_vw_plano_contas.sql, que as traz por extenso.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from filings import rebuild_filings  # noqa: E402
from test_views_plano_contas import (BAL_B3SA, BAL_IRBR, BAL_ITUB, B3SA, BBAS, DRE_B3SA, DRE_BBAS,  # noqa: E402
                                     DRE_IRBR, DRE_ITUB, IRBR, ITUB, MIGRACAO, MIGRACAO_FILINGS,
                                     _balanco, _db, _dre, _migracao)

VIEWS = ["vw_plano_contas", "vw_dre", "vw_dre_acumulada", "vw_dre_financeiro", "vw_dre_seguradora", "vw_balanco"]
COLS = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
        "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]


def _linha(cnpj, fonte, tipo, data, versao, ordem, ini, fim, cd, ds, vl):
    return (cnpj, fonte, tipo, data, versao, ordem, ini, fim, cd, ds, vl, "S")


def _inserir(conn, *linhas):
    conn.executemany("INSERT INTO demonstrativos_contabeis (" + ",".join(COLS) + ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", linhas)


def _cenario(conn):
    """Casos que as views tratam de forma própria: plano por empresa, trimestre isolado x acumulado,
    reapresentação (versão 2 só em parte das contas), coluna Penúltimo, filing sem 3.01, BP sem DRE."""
    _dre(conn, ITUB, DRE_ITUB)
    _dre(conn, BBAS, DRE_BBAS)
    _dre(conn, IRBR, DRE_IRBR)
    _dre(conn, B3SA, DRE_B3SA)
    _balanco(conn, ITUB, BAL_ITUB)
    _balanco(conn, IRBR, BAL_IRBR)
    _balanco(conn, B3SA, BAL_B3SA)
    # ITR 2T: trimestre isolado e acumulado, padrão e banco
    for ini, mult in (("2025-04-01", 1), ("2025-01-01", 2)):
        _dre(conn, B3SA, {k: (d, v * mult) for k, (d, v) in DRE_B3SA.items()}, fonte="ITR",
             data="2025-06-30", ini=ini)
        _dre(conn, ITUB, {k: (d, v * mult) for k, (d, v) in DRE_ITUB.items()}, fonte="ITR",
             data="2025-06-30", ini=ini)
    # reapresentação: versão 2 do DFP da B3 só com parte das contas; a 1 não pode vazar
    _inserir(conn, _linha(B3SA, "DFP", "DRE", "2025-12-31", 2, "Último", "2025-01-01", "2025-12-31", "3.01", "Receita de Venda de Bens e/ou Serviços", 99999e6),
             _linha(B3SA, "DFP", "DRE", "2025-12-31", 2, "Último", "2025-01-01", "2025-12-31", "3.11", "Lucro", 1234e6))
    # coluna Penúltimo (exercício anterior no mesmo filing) não entra em nenhuma view
    _inserir(conn, _linha(B3SA, "DFP", "DRE", "2025-12-31", 2, "Penúltimo", "2024-01-01", "2024-12-31", "3.01", "Receita", 7.0))
    # filing sem 3.01 e balanço sem DRE (plano indefinido → 'padrao' nas views)
    _dre(conn, B3SA, {"3.11": ("Lucro", 1)}, data="2024-12-31", ini="2024-01-01")
    _balanco(conn, B3SA, BAL_B3SA, data="2023-12-31")
    # BPA e BPP com versões diferentes no mesmo filing
    _inserir(conn, _linha(B3SA, "DFP", "BPP", "2025-12-31", 3, "Último", None, "2025-12-31", "2.03", "PL", 5e6))
    rebuild_filings(conn)


def _todas(conn, view):
    cur = conn.execute(f"SELECT * FROM {view}")
    return cur.fetchall()


def test_views_novas_equivalem_as_antigas():
    novo = _db()
    _cenario(novo)
    antigo = _db()
    for v in reversed(VIEWS):
        antigo.execute(f"DROP VIEW {v}")
    antigo.executescript(_migracao(MIGRACAO))      # views antigas, que não leem `filings`
    _cenario(antigo)
    for v in VIEWS:
        a, n = _todas(antigo, v), _todas(novo, v)
        assert a, f"{v} vazia: o cenário não exercita a view"
        assert sorted(a, key=repr) == sorted(n, key=repr), v
    # a reapresentação vale (versão 2) e o balanço tem a versão vigente de cada BPA/BPP
    assert novo.execute("SELECT receita_liquida, lucro_liquido FROM vw_dre WHERE cnpj_companhia = ? AND fonte = 'DFP' "
                        "AND data_referencia = '2025-12-31'", (B3SA,)).fetchone() == (99999e6, 1234e6)
    assert novo.execute("SELECT patrimonio_liquido FROM vw_balanco WHERE cnpj_companhia = ? AND data_referencia = '2025-12-31'",
                        (B3SA,)).fetchone() == (5e6,)


def test_filings_versao_plano_e_periodo():
    conn = _db()
    _cenario(conn)
    f = {(c, fo, t, d): rest for c, fo, t, d, *rest in conn.execute(
        "SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, versao, plano_contas, dt_ini_min, dt_ini_max, n_linhas FROM filings")}
    assert f[(B3SA, "DFP", "DRE", "2025-12-31")][:4] == [2, "padrao", "2025-01-01", "2025-01-01"]
    assert f[(ITUB, "ITR", "DRE", "2025-06-30")][:4] == [1, "banco", "2025-01-01", "2025-04-01"]   # acumulado x isolado
    assert f[(ITUB, "DFP", "BPA", "2025-12-31")][:2] == [1, "banco"]                               # plano replicado da DRE
    assert f[(B3SA, "DFP", "BPP", "2025-12-31")][0] == 3                                           # versão por tipo_doc
    assert f[(B3SA, "DFP", "DRE", "2024-12-31")][1] is None                                        # sem 3.01
    assert f[(B3SA, "DFP", "BPA", "2023-12-31")][1] is None                                        # sem DRE
    assert f[(B3SA, "DFP", "BPA", "2025-12-31")][3:] == [None, 3]                                  # BPA: sem período, 3 linhas
    # Penúltimo não gera filing nem entra na contagem
    assert conn.execute("SELECT COUNT(*) FROM filings WHERE data_referencia = '2024-12-31' AND cnpj_companhia = ?", (B3SA,)).fetchone() == (1,)


def test_rebuild_e_idempotente_e_acompanha_a_ingestao():
    conn = _db()
    _cenario(conn)
    antes = conn.execute("SELECT * FROM filings ORDER BY 1, 2, 3, 4").fetchall()
    assert rebuild_filings(conn) == len(antes)
    assert conn.execute("SELECT * FROM filings ORDER BY 1, 2, 3, 4").fetchall() == antes
    # reapresentação nova (versão 3) só aparece depois da reconstrução
    _inserir(conn, _linha(B3SA, "DFP", "DRE", "2025-12-31", 3, "Último", "2025-01-01", "2025-12-31", "3.01", "Receita de Venda de Bens e/ou Serviços", 1e6))
    rebuild_filings(conn)
    assert conn.execute("SELECT receita_liquida FROM vw_dre WHERE cnpj_companhia = ? AND fonte = 'DFP' "
                        "AND data_referencia = '2025-12-31'", (B3SA,)).fetchone() == (1e6,)


def test_migracao_filings_preenche_igual_ao_rebuild():
    esperado = _db()
    _cenario(esperado)
    conn = _db()
    _cenario(conn)
    conn.execute("DROP TABLE filings")
    for v in reversed(VIEWS):
        conn.execute(f"DROP VIEW {v}")
    for _ in range(2):   # idempotente
        conn.executescript(_migracao(MIGRACAO_FILINGS))
    q = "SELECT * FROM filings ORDER BY 1, 2, 3, 4"
    assert conn.execute(q).fetchall() == esperado.execute(q).fetchall()
    v = "SELECT name, sql FROM sqlite_master WHERE type IN ('view', 'index') AND name LIKE 'vw_%' OR name LIKE 'idx_filings%' ORDER BY name"
    assert conn.execute(v).fetchall() == esperado.execute(v).fetchall()
