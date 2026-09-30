"""
Views de demonstrativos por plano de contas: vw_plano_contas, vw_dre / vw_dre_acumulada /
vw_balanco só no plano padrão, vw_dre_financeiro (bancos) e vw_dre_seguradora.

Fixtures com os nomes e valores dos DFP 2025 (R$ mi) de ITUB4, BBAS3, IRBR3 e B3SA3.
"""
import os
import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
MIGRACOES = os.path.join(os.path.dirname(__file__), "..", "scripts", "migrations")
MIGRACAO = os.path.join(MIGRACOES, "2026-09-30_vw_plano_contas.sql")
MIGRACAO_EBT = os.path.join(MIGRACOES, "2026-09-29_vw_dre_ebt_3_07.sql")

ITUB = "60.872.504/0001-23"
BBAS = "00.000.000/0001-91"
IRBR = "33.376.989/0001-91"
B3SA = "09.346.601/0001-25"

# Itaú: layout de 9 linhas, lucro em 3.09
DRE_ITUB = {"3.01": ("Receitas da Intermediação Financeira", 387118), "3.02": ("Despesas da Intermediação Financeira", -248171),
            "3.03": ("Resultado Bruto Intermediação Financeira", 138947), "3.04": ("Outras Despesas/Receitas Operacionais", -88697),
            "3.05": ("Resultado Antes dos Tributos sobre o Lucro", 50250),
            "3.06": ("Imposto de Renda e Contribuição Social sobre o Lucro", -4401),
            "3.07": ("Resultado Líquido das Operações Continuadas", 45849),
            "3.08": ("Resultado Líquido das Operações Descontinuadas", 0),
            "3.09": ("Lucro/Prejuízo Consolidado do Período", 45849),
            "3.09.01": ("Atribuído a Sócios da Empresa Controladora", 44857),
            "3.09.02": ("Atribuído a Sócios Não Controladores", 992)}
# Banco do Brasil desde 2020: layout de 11 linhas, 3.09 é antes das participações e o lucro é 3.11
# (3.10 sintético para as duas linhas não coincidirem)
DRE_BBAS = {"3.01": ("Receitas de Intermediação Financeira", 319462), "3.02": ("Despesas de Intermediação Financeira", -218451),
            "3.03": ("Resultado Bruto de Intermediação Financeira", 101011), "3.04": ("Outras Despesas e Receitas Operacionais", -95397),
            "3.05": ("Resultado antes dos Tributos sobre o Lucro", 5614),
            "3.06": ("Imposto de Renda e Contribuição Social sobre o Lucro", 11168),
            "3.07": ("Lucro ou Prejuízo das Operações Continuadas", 16782),
            "3.08": ("Resultado Líquido das Operações Descontinuadas", 0),
            "3.09": ("Lucro ou Prejuízo antes das Participações e Contribuições Estatutárias", 16782),
            "3.09.01": ("Participações sintéticas", 1),
            "3.10": ("Participações nos Lucros e Contribuições Estatutárias", -500),
            "3.11": ("Lucro ou Prejuízo Líquido Consolidado do Período", 16282),
            "3.11.01": ("Atribuído aos Sócios da Empresa Controladora", 13198),
            "3.11.02": ("Atribuído aos Sócios não Controladores", 3084)}
# IRB: layout de 13 linhas das seguradoras
DRE_IRBR = {"3.01": ("Receitas das Atividades Seguradoras/Resseguradoras", 5211), "3.02": ("Despesas da Atividade Seguradora/Resseguradora", -4633),
            "3.03": ("Resultado Bruto", 579), "3.04": ("Despesas Administrativas", -30),
            "3.05": ("Outras Receitas e Despesas Operacionais", 11), "3.06": ("Resultado de Equivalência Patrimonial", 0),
            "3.07": ("Resultado Antes do Resultado Financeiro e dos Tributos", 560), "3.08": ("Resultado Financeiro", 43),
            "3.09": ("Resultado Antes dos Tributos sobre o Lucro", 603),
            "3.10": ("Imposto de Renda e Contribuição Social sobre o Lucro", -212),
            "3.11": ("Resultado Líquido das Operações Continuadas", 391),
            "3.12": ("Resultado Líquido de Operações Descontinuadas", 0),
            "3.13": ("Lucro/Prejuízo Consolidado do Período", 391),
            "3.13.01": ("Atribuído a Sócios da Empresa Controladora", 391)}
# B3: setor 'Financeiro', plano padrão
DRE_B3SA = {"3.01": ("Receita de Venda de Bens e/ou Serviços", 11122), "3.02": ("Custo dos Bens e/ou Serviços Vendidos", -1053),
            "3.03": ("Resultado Bruto", 10068), "3.05": ("Resultado Antes do Resultado Financeiro e dos Tributos", 6638),
            "3.06": ("Resultado Financeiro", 308), "3.07": ("Resultado Antes dos Tributos sobre o Lucro", 6946),
            "3.08": ("Imposto de Renda e Contribuição Social sobre o Lucro", -2359),
            "3.11": ("Lucro/Prejuízo Consolidado do Período", 4587)}
BAL_ITUB = {("BPA", "1"): ("Ativo Total", 3066169), ("BPA", "1.01"): ("Caixa e Equivalentes de Caixa", 40000),
            ("BPP", "2.02.01"): ("Derivativos", 90000), ("BPP", "2.03"): ("Passivos Financeiros ao Custo Amortizado", 2500000),
            ("BPP", "2.08"): ("Patrimônio Líquido Consolidado", 230000)}
BAL_IRBR = {("BPA", "1"): ("Ativo Total", 15644), ("BPA", "1.01"): ("Ativo Circulante", 6302),
            ("BPA", "1.01.01"): ("Caixa e Equivalentes de Caixa", 11), ("BPP", "2.01.04"): ("Provisões Técnicas", 4000),
            ("BPP", "2.02.01"): ("Passivo Exigível a Longo Prazo", 3000), ("BPP", "2.03"): ("Patrimônio Líquido Consolidado", 5283)}
BAL_B3SA = {("BPA", "1"): ("Ativo Total", 48488), ("BPA", "1.01"): ("Ativo Circulante", 17712),
            ("BPA", "1.01.01"): ("Caixa e Equivalentes de Caixa", 1604), ("BPP", "2.01.04"): ("Empréstimos e Financiamentos", 871),
            ("BPP", "2.02.01"): ("Empréstimos e Financiamentos", 14074), ("BPP", "2.03"): ("Patrimônio Líquido Consolidado", 17464)}

COLS = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
        "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]


def _db(schema=None):
    conn = sqlite3.connect(":memory:")
    if schema is None:
        with open(SCHEMA, encoding="utf-8") as f:
            schema = f.read()
    conn.executescript(schema)
    return conn


def _migracao(caminho):
    with open(caminho, encoding="utf-8") as f:
        # dot-commands (.bail on) são do cliente sqlite3, não SQL
        return "".join(l for l in f if not l.startswith("."))


def _dre(conn, cnpj, contas, fonte="DFP", data="2025-12-31", ini="2025-01-01", mult=1e6):
    conn.executemany(f"INSERT INTO demonstrativos_contabeis ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                     [(cnpj, fonte, "DRE", data, 1, "Último", ini, data, cd, ds, vl * mult, "S")
                      for cd, (ds, vl) in contas.items()])


def _balanco(conn, cnpj, contas, fonte="DFP", data="2025-12-31"):
    conn.executemany(f"INSERT INTO demonstrativos_contabeis ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                     [(cnpj, fonte, tipo, data, 1, "Último", None, data, cd, ds, vl * 1e6, "S")
                      for (tipo, cd), (ds, vl) in contas.items()])


def _carregar(conn):
    _dre(conn, ITUB, DRE_ITUB)
    _dre(conn, BBAS, DRE_BBAS)
    _dre(conn, IRBR, DRE_IRBR)
    _dre(conn, B3SA, DRE_B3SA)
    _balanco(conn, ITUB, BAL_ITUB)
    _balanco(conn, IRBR, BAL_IRBR)
    _balanco(conn, B3SA, BAL_B3SA)
    return conn


def _um(conn, sql, *params):
    cur = conn.execute(sql, params)
    nomes = [c[0] for c in cur.description]
    linhas = [dict(zip(nomes, r)) for r in cur.fetchall()]
    assert len(linhas) == 1, linhas
    return linhas[0]


def test_plano_contas_pelo_nome_da_conta_3_01():
    conn = _carregar(_db())
    # seguradora antes de 2023 (antes da troca de nomes do IFRS 17)
    _dre(conn, IRBR, {"3.01": ("Receitas das Operações", 7047), "3.13": ("Lucro/Prejuízo Consolidado do Período", -630)},
         data="2022-12-31", ini="2022-01-01")
    # filing sem 3.01 não é classificado (as views o tratam como padrão)
    _dre(conn, B3SA, {"3.11": ("Lucro", 1)}, data="2024-12-31", ini="2024-01-01")
    got = conn.execute("SELECT cnpj_companhia, data_referencia, plano_contas FROM vw_plano_contas ORDER BY 1, 2").fetchall()
    assert got == [(BBAS, "2025-12-31", "banco"), (B3SA, "2025-12-31", "padrao"),
                   (IRBR, "2022-12-31", "seguradora"), (IRBR, "2025-12-31", "seguradora"),
                   (ITUB, "2025-12-31", "banco")]


def test_vw_dre_nula_fora_do_plano_padrao():
    """Regressão: no DFP 2025 do Itaú a view devolvia 3.01 como receita_liquida, 3.05 (LAIR) como ebit,
    3.07 (operações continuadas) como ebt e lucro_liquido NULL."""
    conn = _carregar(_db())
    for view in ("vw_dre", "vw_dre_acumulada"):
        for cnpj, plano in ((ITUB, "banco"), (BBAS, "banco"), (IRBR, "seguradora")):
            r = _um(conn, f"SELECT * FROM {view} WHERE cnpj_companhia = ?", cnpj)
            valores = {k: v for k, v in r.items() if k not in ("cnpj_companhia", "fonte", "data_referencia",
                                                                 "dt_ini_exerc", "dt_fim_exerc", "plano_contas")}
            assert set(valores.values()) == {None}, (view, cnpj, valores)
            assert (r["plano_contas"], r["dt_fim_exerc"]) == (plano, "2025-12-31")   # a linha do filing continua lá
        r = _um(conn, f"SELECT * FROM {view} WHERE cnpj_companhia = ?", B3SA)          # setor Financeiro, plano padrão
        assert (r["receita_liquida"], r["ebit"], r["ebt"], r["lucro_liquido"], r["plano_contas"]) == \
            (11122e6, 6638e6, 6946e6, 4587e6, "padrao")


def test_vw_dre_financeiro_nos_dois_layouts_de_banco():
    conn = _carregar(_db())
    r = _um(conn, "SELECT * FROM vw_dre_financeiro WHERE cnpj_companhia = ?", ITUB)
    assert (r["receita_intermediacao"], r["despesa_intermediacao"], r["resultado_bruto_intermediacao"],
            r["outras_receitas_despesas_operacionais"], r["lair"], r["ir_cs"], r["lucro_liquido"], r["lucro_controladora"]) == \
        (387118e6, -248171e6, 138947e6, -88697e6, 50250e6, -4401e6, 45849e6, 44857e6)
    r = _um(conn, "SELECT * FROM vw_dre_financeiro WHERE cnpj_companhia = ?", BBAS)
    # 11 linhas: o lucro é 3.11, não 3.09 (antes das participações), e a controladora é 3.11.01
    assert (r["lair"], r["lucro_liquido"], r["lucro_controladora"]) == (5614e6, 16282e6, 13198e6)
    assert conn.execute("SELECT COUNT(*) FROM vw_dre_financeiro WHERE cnpj_companhia IN (?, ?)", (IRBR, B3SA)).fetchone() == (0,)


def test_vw_dre_financeiro_trimestre_isolado_no_itr():
    conn = _db()
    tri = {"3.01": ("Receitas da Intermediação Financeira", 100), "3.09": ("Lucro/Prejuízo Consolidado do Período", 11.6)}
    acu = {"3.01": ("Receitas da Intermediação Financeira", 290), "3.09": ("Lucro/Prejuízo Consolidado do Período", 33.0)}
    _dre(conn, ITUB, tri, fonte="ITR", data="2025-09-30", ini="2025-07-01", mult=1e9)
    _dre(conn, ITUB, acu, fonte="ITR", data="2025-09-30", ini="2025-01-01", mult=1e9)
    r = _um(conn, "SELECT * FROM vw_dre_financeiro WHERE cnpj_companhia = ?", ITUB)
    assert (r["dt_ini_exerc"], r["receita_intermediacao"], r["lucro_liquido"]) == ("2025-07-01", 100e9, 11.6e9)


def test_vw_dre_seguradora():
    conn = _carregar(_db())
    r = _um(conn, "SELECT * FROM vw_dre_seguradora WHERE cnpj_companhia = ?", IRBR)
    assert (r["receita_operacoes"], r["despesa_operacoes"], r["resultado_bruto"], r["despesas_administrativas"],
            r["outras_receitas_despesas_operacionais"], r["equivalencia_patrimonial"], r["ebit"], r["resultado_financeiro"],
            r["ebt"], r["ir_cs"], r["lucro_liquido"], r["lucro_controladora"]) == \
        (5211e6, -4633e6, 579e6, -30e6, 11e6, 0.0, 560e6, 43e6, 603e6, -212e6, 391e6, 391e6)
    assert conn.execute("SELECT COUNT(*) FROM vw_dre_seguradora WHERE cnpj_companhia <> ?", (IRBR,)).fetchone() == (0,)


def test_vw_balanco_por_plano():
    conn = _carregar(_db())
    campos = "ativo_total, ativo_circulante, caixa, divida_curto_prazo, divida_longo_prazo, patrimonio_liquido, plano_contas"
    q = f"SELECT {campos} FROM vw_balanco WHERE cnpj_companhia = ?"
    # banco: só o ativo total tem o mesmo significado (2.03 seria "Passivos Financeiros ao Custo Amortizado" como PL)
    assert conn.execute(q, (ITUB,)).fetchone() == (3066169e6, None, None, None, None, None, "banco")
    # seguradora: 2.01.04/2.02.01 são provisões técnicas e exigível a longo prazo, não dívida
    assert conn.execute(q, (IRBR,)).fetchone() == (15644e6, 6302e6, 11e6, None, None, 5283e6, "seguradora")
    assert conn.execute(q, (B3SA,)).fetchone() == (48488e6, 17712e6, 1604e6, 871e6, 14074e6, 17464e6, "padrao")


def test_migracao_plano_contas_corrige_banco_existente_e_espelha_schema():
    views = "SELECT name, sql FROM sqlite_master WHERE type = 'view' ORDER BY name"
    # banco anterior: views de antes desta migração (vw_dre/vw_dre_acumulada da migração do EBT,
    # vw_balanco sem plano_contas, sem vw_plano_contas / vw_dre_financeiro / vw_dre_seguradora)
    conn = _db()
    with open(SCHEMA, encoding="utf-8") as f:
        schema = f.read()
    for v in ("vw_balanco", "vw_dre_seguradora", "vw_dre_financeiro", "vw_dre_acumulada", "vw_dre", "vw_plano_contas"):
        conn.execute(f"DROP VIEW {v}")
    conn.executescript(_migracao(MIGRACAO_EBT))
    _carregar(conn)
    assert conn.execute("SELECT receita_liquida FROM vw_dre WHERE cnpj_companhia = ?", (ITUB,)).fetchone() == (387118e6,)  # o bug
    for _ in range(2):  # idempotente
        conn.executescript(_migracao(MIGRACAO))
    assert conn.execute("SELECT receita_liquida, plano_contas FROM vw_dre WHERE cnpj_companhia = ?", (ITUB,)).fetchone() == \
        (None, "banco")
    assert conn.execute("SELECT lucro_liquido FROM vw_dre_financeiro WHERE cnpj_companhia = ?", (ITUB,)).fetchone() == (45849e6,)
    assert conn.execute(views).fetchall() == _db(schema).execute(views).fetchall()
