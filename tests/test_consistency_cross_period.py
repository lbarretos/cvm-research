"""
Fase 1 da consistência financeira: Camada 2 (cruzamento entre filings).
Testa a lógica pura (DataFrame → flags), sem banco.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_cross_period as ccp

CNPJ = "84.429.695/0001-11"
BPA = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 60e6), "1.02": ("Ativo Não Circulante", 40e6)}


def _doc(fonte, data_ref, ordem, p_ini, p_fim, contas, tipo_doc="BPA"):
    """Linhas de um documento para UM período, no formato de latest_rows."""
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": p_ini, "periodo_fim": p_fim,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": vl, "st_conta_fixa": "S"}
            for cd, (ds, vl) in contas.items()]


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


def _dfp23(contas=BPA):
    return _doc("DFP", "2023-12-31", "Último", "NA", "2023-12-31", contas)


def _itr1t24(contas=BPA):
    return _doc("ITR", "2024-03-31", "Penúltimo", "NA", "2023-12-31", contas)


def _resumos(flags):
    return [f for f in flags if f["cd_conta"] is None]


def _linhas(flags):
    return [f for f in flags if f["cd_conta"] is not None]


def test_pares_iguais_nao_geram_flags():
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24()))
    assert flags == []
    assert stats == {"BPA": {"pares": 1, "pares_divergentes": 0, "reapresentacao": 0}}


def test_dataframe_vazio():
    assert ccp.check_cross_period(pd.DataFrame()) == ([], {})


def test_total_diverge_e_reapresentacao_warn():
    cmp = {"1": ("Ativo Total", 110e6), "1.01": ("Ativo Circulante", 70e6), "1.02": ("Ativo Não Circulante", 40e6)}
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert stats["BPA"] == {"pares": 1, "pares_divergentes": 1, "reapresentacao": 1}
    assert {f["classificacao"] for f in flags} == {"reapresentacao"}
    assert {f["severity"] for f in flags} == {"warn"}
    linhas = {f["cd_conta"]: f for f in _linhas(flags)}
    assert set(linhas) == {"1", "1.01"}
    total = linhas["1"]
    assert (total["layer"], total["check_type"], total["cnpj_companhia"], total["tipo_doc"]) == \
        (2, "cross_period", CNPJ, "BPA")
    assert (total["periodo_ini"], total["periodo_fim"]) == ("NA", "2023-12-31")
    assert (total["fonte_ref"], total["data_ref"], total["ordem_ref"]) == ("DFP", "2023-12-31", "Último")
    assert (total["fonte_cmp"], total["data_cmp"], total["ordem_cmp"]) == ("ITR", "2024-03-31", "Penúltimo")
    assert (total["valor_ref"], total["valor_cmp"], total["diff_abs"]) == (100e6, 110e6, 10e6)
    assert abs(total["diff_rel"] - 0.1) < 1e-12
    assert total["ds_conta"] == "Ativo Total" and total["cd_conta_pai"] is None
    assert linhas["1.01"]["cd_conta_pai"] == "1"
    resumo, = _resumos(flags)
    assert resumo["classificacao"] == "reapresentacao" and resumo["severity"] == "warn"
    assert resumo["fonte_cmp"] == "ITR" and resumo["periodo_fim"] == "2023-12-31"
    assert resumo["detalhe"] == {"linhas_comuns": 3, "linhas_divergentes": 2,
                                 "linhas_exclusivas_ref": 0, "linhas_exclusivas_cmp": 0,
                                 "total_disponivel": True}


def test_sublinha_diverge_e_reclassificacao_info():
    cmp = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 61e6), "1.02": ("Ativo Não Circulante", 39e6)}
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert stats["BPA"] == {"pares": 1, "pares_divergentes": 1, "reapresentacao": 0}
    assert {f["classificacao"] for f in flags} == {"reclassificacao"}
    assert {f["severity"] for f in flags} == {"info"}
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.01", "1.02"}
    assert _resumos(flags)[0]["detalhe"]["linhas_divergentes"] == 2


def test_linha_exclusiva_nao_gera_flag_de_linha():
    cmp = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 60e6), "1.03": ("Outros", 40e6)}
    flags, _ = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert flags == []                       # só exclusivas: Camada 3 cuida; nada aqui
    cmp["1.01"] = ("Ativo Circulante", 62e6)
    flags, _ = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.01"}
    assert _resumos(flags)[0]["detalhe"] == {"linhas_comuns": 2, "linhas_divergentes": 1,
                                             "linhas_exclusivas_ref": 1, "linhas_exclusivas_cmp": 1,
                                             "total_disponivel": True}


def test_baseline_e_o_filing_mais_antigo_mesmo_com_itr_primeiro():
    itr_div = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 65e6), "1.02": ("Ativo Não Circulante", 35e6)}
    dfp24 = _doc("DFP", "2024-12-31", "Penúltimo", "NA", "2023-12-31", BPA)
    flags, stats = ccp.check_cross_period(_df(_itr1t24(itr_div), dfp24, _dfp23()))
    assert stats["BPA"] == {"pares": 2, "pares_divergentes": 1, "reapresentacao": 0}
    assert {(f["fonte_ref"], f["data_ref"]) for f in flags} == {("DFP", "2023-12-31")}
    assert {(f["fonte_cmp"], f["data_cmp"]) for f in flags} == {("ITR", "2024-03-31")}


def test_dre_trimestre_e_acumulado_nao_se_misturam():
    acu = {"3.01": ("Receita", 200e6), "3.11": ("Lucro", 20e6)}
    tri = {"3.01": ("Receita", 120e6), "3.11": ("Lucro", 12e6)}
    df = _df(
        _doc("ITR", "2023-06-30", "Último",    "2023-01-01", "2023-06-30", acu, "DRE"),
        _doc("ITR", "2023-06-30", "Último",    "2023-04-01", "2023-06-30", tri, "DRE"),
        _doc("ITR", "2024-06-30", "Penúltimo", "2023-01-01", "2023-06-30", acu, "DRE"),
        _doc("ITR", "2024-06-30", "Penúltimo", "2023-04-01", "2023-06-30", tri, "DRE"),
    )
    flags, stats = ccp.check_cross_period(df)
    assert flags == []
    assert stats == {"DRE": {"pares": 2, "pares_divergentes": 0, "reapresentacao": 0}}


def test_dre_qualquer_total_divergente_classifica_reapresentacao():
    ref = {"3.01": ("Receita", 200e6), "3.05": ("EBIT", 30e6), "3.11": ("Lucro", 20e6)}
    cmp = {"3.01": ("Receita", 200e6), "3.05": ("EBIT", 30e6), "3.11": ("Lucro", 25e6)}
    df = _df(_doc("DFP", "2023-12-31", "Último",    "2023-01-01", "2023-12-31", ref, "DRE"),
             _doc("DFP", "2024-12-31", "Penúltimo", "2023-01-01", "2023-12-31", cmp, "DRE"))
    flags, stats = ccp.check_cross_period(df)
    assert stats["DRE"]["reapresentacao"] == 1
    assert {f["cd_conta"] for f in _linhas(flags)} == {"3.11"}
    assert {f["classificacao"] for f in flags} == {"reapresentacao"}


def test_dva_total_resolvido_pelo_nome_do_documento():
    ref = {"7.07": ("Vlr Adicionado Recebido em Transferência", 1e6), "7.08": ("Valor Adicionado Total a Distribuir", 50e6)}
    cmp = {"7.07": ("Vlr Adicionado Recebido em Transferência", 1e6), "7.08": ("Valor Adicionado Total a Distribuir", 55e6)}
    df = _df(_doc("DFP", "2023-12-31", "Último",    "2023-01-01", "2023-12-31", ref, "DVA"),
             _doc("DFP", "2024-12-31", "Penúltimo", "2023-01-01", "2023-12-31", cmp, "DVA"))
    flags, stats = ccp.check_cross_period(df)
    assert stats["DVA"]["reapresentacao"] == 1


def test_tolerancia_piso_e_relativa():
    ref = {"1": ("Ativo Total", 1e9), "1.01": ("Ativo Circulante", 50_000.0), "1.02": ("Ativo Não Circulante", 50_000.0)}
    cmp = {"1": ("Ativo Total", 1e9 + 8e6),             # 0,8% < 1% (padrão)
           "1.01": ("Ativo Circulante", 50_900.0),        # +900 < piso 1000 (1% de 50k = 500)
           "1.02": ("Ativo Não Circulante", 51_100.0)}    # +1100 > piso
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)))
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.02"}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)), tol_abs=500.0)
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.01", "1.02"}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)), tol_rel=0.005)
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1", "1.02"}   # 0,8% > 0,5%


def test_vl_conta_nulo_conta_como_zero():
    ref = {"1": ("Ativo Total", 100e6), "1.02": ("Ativo Não Circulante", None)}
    cmp = {"1": ("Ativo Total", 100e6), "1.02": ("Ativo Não Circulante", 5e6)}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)))
    linha, = _linhas(flags)
    assert (linha["cd_conta"], linha["valor_ref"], linha["valor_cmp"], linha["diff_abs"], linha["diff_rel"]) == \
        ("1.02", 0.0, 5e6, 5e6, None)


def test_total_ausente_dos_dois_lados_vira_reclassificacao_sem_total():
    ref = {"1.01": ("Ativo Circulante", 60e6)}
    cmp = {"1.01": ("Ativo Circulante", 70e6)}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)))
    assert {f["classificacao"] for f in flags} == {"reclassificacao"}
    assert _resumos(flags)[0]["detalhe"]["total_disponivel"] is False


def test_empresas_e_tipos_nao_se_cruzam():
    outra = [dict(r, cnpj_companhia="00.000.000/0001-91", vl_conta=r["vl_conta"] * 2) for r in _itr1t24()]
    bpp = _doc("DFP", "2023-12-31", "Último", "NA", "2023-12-31", {"2": ("Passivo Total", 100e6)}, "BPP")
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24(), outra, bpp))
    assert flags == []
    assert stats == {"BPA": {"pares": 1, "pares_divergentes": 0, "reapresentacao": 0}}


def test_iter_pairs_baseline_e_contexto():
    dfp24 = _doc("DFP", "2024-12-31", "Penúltimo", "NA", "2023-12-31", BPA)
    pares = list(ccp.iter_pairs(_df(_itr1t24(), dfp24, _dfp23())))
    assert [(p["fonte_cmp"], p["data_cmp"]) for p, _, _ in pares] == [("ITR", "2024-03-31"), ("DFP", "2024-12-31")]
    par, ref, cmp = pares[0]
    assert par == {"cnpj_companhia": CNPJ, "tipo_doc": "BPA", "periodo_ini": "NA", "periodo_fim": "2023-12-31",
                   "fonte_ref": "DFP", "data_ref": "2023-12-31", "ordem_ref": "Último",
                   "fonte_cmp": "ITR", "data_cmp": "2024-03-31", "ordem_cmp": "Penúltimo"}
    assert set(ref["cd_conta"]) == set(BPA) and set(cmp["fonte"]) == {"ITR"}
    assert list(ccp.iter_pairs(pd.DataFrame())) == []


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db_com_docs():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    cmp = {"1": ("Ativo Total", 110e6), "1.01": ("Ativo Circulante", 70e6), "1.02": ("Ativo Não Circulante", 40e6)}
    rows = _dfp23() + _itr1t24(cmp)
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols) for r in rows],
    )
    conn.commit()
    return conn


def test_main_grava_run_e_flags_e_substitui_anteriores(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(ccp, "get_db", lambda: conn)

    run1 = ccp.main(["--cnpj", CNPJ])
    n1 = conn.execute("SELECT COUNT(*) FROM consistency_flags WHERE run_id = ?", (run1,)).fetchone()[0]
    assert n1 == 3                                              # 2 linhas + 1 resumo
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, finished_at "
                       "FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (2, "cross_period", f"cnpj={CNPJ}", 1, 3) and run[5] is not None

    run2 = ccp.main(["--cnpj", CNPJ, "--tipo-doc", "BPA"])
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 3   # substituiu, não somou
    assert conn.execute("SELECT DISTINCT run_id FROM consistency_flags").fetchone()[0] == run2
    assert conn.execute("SELECT COUNT(*) FROM consistency_runs").fetchone()[0] == 2

    out = capsys.readouterr().out
    assert "BPA" in out and "pares=1" in out and "reapresentacao=1" in out


def test_main_exige_cnpj_ou_full(monkeypatch):
    monkeypatch.setattr(ccp, "get_db", lambda: _db_com_docs())
    import pytest
    with pytest.raises(SystemExit):
        ccp.main([])


def test_main_full_percorre_companies(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(ccp, "get_db", lambda: conn)
    run_id = ccp.main(["--full"])
    escopo = conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert escopo == "full"
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 3
