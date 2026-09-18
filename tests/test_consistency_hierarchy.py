"""
Fase 2 da consistência financeira: Camada 1 (soma hierárquica intra-documento).
Testa a lógica pura (DataFrame → flags), sem banco; main() ao final com banco em memória.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_hierarchy_sums as chs

CNPJ = "84.429.695/0001-11"
BPA_OK = {
    "1":       ("Ativo Total", 100e6),
    "1.01":    ("Ativo Circulante", 60e6),
    "1.01.01": ("Caixa", 25e6),
    "1.01.02": ("Contas a Receber", 35e6),
    "1.02":    ("Ativo Não Circulante", 40e6),
}


def _doc(contas, tipo_doc="BPA", fonte="DFP", data_ref="2023-12-31", ordem="Último",
         p_ini="NA", p_fim="2023-12-31"):
    """Linhas de UM (documento, ordem, período), no formato de latest_rows."""
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": p_ini, "periodo_fim": p_fim,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": vl, "st_conta_fixa": "S"}
            for cd, (ds, vl) in contas.items()]


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


def _por_conta(flags):
    return {f["cd_conta"]: f for f in flags}


# ── check_document ───────────────────────────────────────────────────────────

def test_arvore_que_bate_nao_gera_flag():
    flags, checados = chs.check_document(pd.DataFrame(_doc(BPA_OK)), "BPA")
    assert flags == []
    assert checados == 2                         # pais "1" e "1.01"


def test_nao_detalhado_pai_preenchido_filhos_zero_ou_nulos():
    contas = dict(BPA_OK, **{"1.01.01": ("Caixa", 0.0), "1.01.02": ("Contas a Receber", None)})
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01", "nao_detalhado", "info")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"], f["diff_rel"]) == (60e6, 0.0, -60e6, -1.0)
    assert f["cd_conta_pai"] == "1" and f["ds_conta"] == "Ativo Circulante"
    assert f["detalhe"] == {"regra": "soma", "filhos": ["1.01.01", "1.01.02"], "filhos_nao_zero": 0}


def test_pai_vazio_pai_nulo_ou_zero_com_filho_preenchido():
    contas = dict(BPA_OK, **{"1.01": ("Ativo Circulante", None)})
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    por = _por_conta(flags)
    assert por["1.01"]["classificacao"] == "pai_vazio" and por["1.01"]["severity"] == "warn"
    assert (por["1.01"]["valor_ref"], por["1.01"]["valor_cmp"], por["1.01"]["diff_rel"]) == (0.0, 60e6, None)
    assert por["1"]["classificacao"] == "divergencia"          # 1 = 100 ≠ 0 + 40
    contas["1.01"] = ("Ativo Circulante", 0.0)
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    assert _por_conta(flags)["1.01"]["classificacao"] == "pai_vazio"


def test_divergencia_pai_e_filhos_preenchidos_mas_nao_batem():
    contas = dict(BPA_OK, **{"1.01.02": ("Contas a Receber", 30e6)})
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01", "divergencia", "error")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == (60e6, 55e6, -5e6)
    assert abs(f["diff_rel"] + 5e6 / 60e6) < 1e-12
    assert f["detalhe"]["filhos_nao_zero"] == 2


def test_excecao_6_05_saldo_final_menos_inicial():
    dfc = {"6.01": ("Operacional", 10e6), "6.02": ("Investimento", -4e6), "6.03": ("Financiamento", -3e6),
           "6.04": ("Variação Cambial", 0.0), "6.05": ("Aumento (Redução) de Caixa", 3e6),
           "6.05.01": ("Saldo Inicial", 20e6), "6.05.02": ("Saldo Final", 23e6)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dfc, "DFC_MI", p_ini="2023-01-01")), "DFC_MI")
    assert flags == []                            # soma simples daria 43e6; saldo dá 3e6
    assert checados == 2                          # pai 6.05 + fórmula 6.05
    dfc["6.05.02"] = ("Saldo Final", 24e6)
    flags, _ = chs.check_document(pd.DataFrame(_doc(dfc, "DFC_MI", p_ini="2023-01-01")), "DFC_MI")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["valor_cmp"]) == ("6.05", "divergencia", 4e6)
    assert f["detalhe"]["regra"] == "saldo"


def test_excecao_3_99_lucro_por_acao_ignorado():
    dre = {"3.99": ("Lucro por Ação", 1.5), "3.99.01": ("Básico", 1.5), "3.99.02": ("Diluído", 1.4),
           "3.99.01.01": ("ON", 1.5), "3.99.01.02": ("PN", 1.65)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE",
                                         formulas=False)
    assert flags == [] and checados == 0


def test_formula_nivel2_com_custo_negativo():
    dre = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 40e6),
           "3.04": ("Despesas", -10e6), "3.05": ("EBIT", 30e6)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    assert flags == []
    assert checados == 2                          # fórmulas 3.03 e 3.05 (3.07/3.09/3.11 ausentes: puladas)
    dre["3.05"] = ("EBIT", 35e6)
    flags, _ = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("3.05", "divergencia_formula", "error")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == (35e6, 30e6, -5e6)
    assert f["cd_conta_pai"] == "3" and f["ds_conta"] == "EBIT"
    assert f["detalhe"] == {"regra": "formula", "formula": "3.05 = 3.03 + 3.04",
                            "termos": {"3.03": 40e6, "3.04": -10e6}}


def test_formula_termo_ausente_conta_como_zero_e_formulas_false_pula():
    dre = {"3.01": ("Receita", 100e6), "3.03": ("Resultado Bruto", 100e6)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    assert flags == [] and checados == 1
    dre["3.03"] = ("Resultado Bruto", 90e6)
    flags, _ = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    assert [f["classificacao"] for f in flags] == ["divergencia_formula"]
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE",
                                         formulas=False)
    assert flags == [] and checados == 0


def test_tolerancia_piso_e_relativa():
    contas = {"1": ("Ativo Total", 1e9), "1.01": ("Ativo Circulante", 1e9 + 4e6),        # 0,4%
              "2": ("Passivo Total", 50_000.0), "2.01": ("Circulante", 50_900.0)}        # +900 < piso
    doc = pd.DataFrame(_doc(contas))
    assert chs.check_document(doc, "BPA", tol_rel=0.005)[0] == []
    assert {f["cd_conta"] for f in chs.check_document(doc, "BPA", tol_rel=0.001)[0]} == {"1"}
    assert {f["cd_conta"] for f in chs.check_document(doc, "BPA", tol_abs=500.0)[0]} == {"2"}


# ── check_hierarchy_sums (agrupamento) ───────────────────────────────────────

def test_grupos_por_documento_ordem_e_periodo():
    tri = {"3.01": ("Receita", 50e6), "3.02": ("Custo", -30e6), "3.03": ("Resultado Bruto", 20e6)}
    acu = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 45e6)}   # 45 ≠ 40
    pen = {"3.01": ("Receita", 90e6), "3.02": ("Custo", -50e6), "3.03": ("Resultado Bruto", 40e6)}
    df = _df(
        _doc(tri, "DRE", "ITR", "2023-06-30", "Último",    "2023-04-01", "2023-06-30"),
        _doc(acu, "DRE", "ITR", "2023-06-30", "Último",    "2023-01-01", "2023-06-30"),
        _doc(pen, "DRE", "ITR", "2023-06-30", "Penúltimo", "2022-01-01", "2022-06-30"),
    )
    flags, stats = chs.check_hierarchy_sums(df)
    f, = flags
    assert (f["periodo_ini"], f["periodo_fim"], f["ordem_ref"]) == ("2023-01-01", "2023-06-30", "Último")
    assert (f["layer"], f["check_type"], f["cnpj_companhia"], f["tipo_doc"]) == (1, "hierarchy_sum", CNPJ, "DRE")
    assert (f["fonte_ref"], f["data_ref"]) == ("ITR", "2023-06-30")
    assert f.get("fonte_cmp") is None and f.get("data_cmp") is None
    assert stats == {"DRE": {"grupos": 3, "pais": 3, "nao_detalhado": 0, "pai_vazio": 0,
                             "divergencia": 0, "divergencia_formula": 1}}


def test_formulas_desligadas_para_o_dataframe_inteiro():
    dre = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 45e6)}
    flags, stats = chs.check_hierarchy_sums(_df(_doc(dre, "DRE", p_ini="2023-01-01")), formulas=False)
    assert flags == [] and stats["DRE"]["pais"] == 0


def test_dataframe_vazio():
    assert chs.check_hierarchy_sums(pd.DataFrame()) == ([], {})


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
BANCO = "60.746.948/0001-12"


def _db_com_docs():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.executemany("INSERT INTO companies (cnpj, ticker, nome_cvm, setor) VALUES (?,?,?,?)",
                     [(CNPJ, "WEGE3", "WEG", "Industrial"), (BANCO, "BBDC4", "BRADESCO", "Financeiro")])
    bpa = dict(BPA_OK, **{"1.01.01": ("Caixa", 0.0), "1.01.02": ("Contas a Receber", 0.0)})   # nao_detalhado em 1.01
    dre = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 45e6)}  # fórmula falha
    rows = (_doc(bpa) + _doc(dre, "DRE", p_ini="2023-01-01")
            + [dict(r, cnpj_companhia=BANCO) for r in _doc(dre, "DRE", p_ini="2023-01-01")])
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(None if (c == "dt_ini_exerc" and r["periodo_ini"] == "NA") else
               r["periodo_ini"] if c == "dt_ini_exerc" else
               r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols) for r in rows],
    )
    conn.commit()
    return conn


def test_main_grava_run_e_flags_e_substitui_anteriores(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(chs, "get_db", lambda: conn)

    run1 = chs.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT tipo_doc, cd_conta, classificacao, severity FROM consistency_flags "
                       "WHERE run_id = ? ORDER BY tipo_doc", (run1,)).fetchall()
    assert got == [("BPA", "1.01", "nao_detalhado", "info"), ("DRE", "3.03", "divergencia_formula", "error")]
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, finished_at "
                       "FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (1, "hierarchy_sum", f"cnpj={CNPJ}", 3, 2) and run[5] is not None   # pais 1, 1.01 + fórmula 3.03

    run2 = chs.main(["--cnpj", CNPJ, "--tipo-doc", "BPA"])
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 2   # substituiu a BPA, manteve a DRE
    assert conn.execute("SELECT run_id FROM consistency_flags WHERE tipo_doc = 'BPA'").fetchone()[0] == run2
    assert conn.execute("SELECT run_id FROM consistency_flags WHERE tipo_doc = 'DRE'").fetchone()[0] == run1

    out = capsys.readouterr().out
    assert "BPA" in out and "nao_detalhado=1" in out and "divergencia_formula=1" in out


def test_main_full_pula_formulas_no_setor_financeiro(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(chs, "get_db", lambda: conn)
    run_id = chs.main(["--full"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    got = conn.execute("SELECT cnpj_companhia, classificacao FROM consistency_flags ORDER BY 1, 2").fetchall()
    assert got == [(CNPJ, "divergencia_formula"), (CNPJ, "nao_detalhado")]   # o banco não gera flag de fórmula


def test_main_exige_cnpj_ou_full(monkeypatch):
    monkeypatch.setattr(chs, "get_db", lambda: _db_com_docs())
    import pytest
    with pytest.raises(SystemExit):
        chs.main([])
