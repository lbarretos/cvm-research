"""
Fase 3 da consistência financeira: Camada 3 (granularidade entre filings).
Lógica pura (DataFrame → flags) sem banco; main() ao final com banco em memória.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_granularity as ccg

CNPJ = "84.429.695/0001-11"
BASE = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 60e6),
        "1.01.01": ("Caixa", 20e6), "1.01.02": ("Contas a Receber", 30e6), "1.01.03": ("Estoques", 10e6),
        "1.02": ("Ativo Não Circulante", 40e6)}


def _doc(contas, fonte="DFP", data_ref="2023-12-31", ordem="Último", p_ini="NA", p_fim="2023-12-31",
         tipo_doc="BPA", st="S"):
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": p_ini, "periodo_fim": p_fim,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": vl,
             "st_conta_fixa": (v[2] if len(v) > 2 else st)}
            for cd, v in contas.items() for ds, vl in [v[:2]]]


def _ref(contas=BASE):
    return _doc(contas)


def _cmp(contas):
    return _doc(contas, "ITR", "2024-03-31", "Penúltimo")


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


def _linhas(flags):
    return [f for f in flags if f["cd_conta"] is not None]


def _resumo(flags):
    r, = [f for f in flags if f["cd_conta"] is None]
    return r


def _classes(flags):
    return {(f["cd_conta"], f["classificacao"]) for f in _linhas(flags)}


def test_sem_exclusivos_nao_gera_flag():
    flags, stats = ccg.check_granularity(_df(_ref(), _cmp(BASE)))
    assert flags == []
    assert stats == {"BPA": {"pares": 1, "pares_com_exclusivos": 0, "renumerado": 0, "zero_padding": 0,
                             "reclassificado_em_outros": 0, "reclassificado_em_irmao": 0,
                             "divergencia_nao_explicada": 0}}
    assert ccg.check_granularity(pd.DataFrame()) == ([], {})


def test_renumerado_por_nome_ignora_acento_e_caixa():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("ESTOQUES", 11e6)
    flags, stats = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["cd_conta_pai"], f["classificacao"], f["severity"]) == ("1.01.03", "1.01", "renumerado", "info")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == (10e6, 11e6, 1e6)
    assert f["detalhe"] == {"casamento": "nome", "cd_ref": "1.01.03", "cd_cmp": "1.01.07"}
    assert (f["layer"], f["check_type"], f["fonte_cmp"], f["data_cmp"]) == (3, "granularity", "ITR", "2024-03-31")
    assert _resumo(flags)["classificacao"] == "renumerado"
    assert _resumo(flags)["detalhe"] == {"linhas_exclusivas_ref": 1, "linhas_exclusivas_cmp": 1, "filhos_de_pai_exclusivo": 0,
                                         "renumerado": 1, "zero_padding": 0, "reclassificado_em_outros": 0,
                                         "reclassificado_em_irmao": 0, "divergencia_nao_explicada": 0}
    assert stats["BPA"]["pares_com_exclusivos"] == 1 and stats["BPA"]["renumerado"] == 1


def test_nome_igual_com_st_conta_fixa_diferente_nao_casa():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("Estoques", 12e6, "N")
    cmp["1.01.01"] = ("Caixa", 18e6)                            # pai 1.01 continua 60e6
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    assert _classes(flags) == {("1.01.03", "reclassificado_em_irmao"), ("1.01.07", "reclassificado_em_irmao")}


def test_zero_padding_valor_pequeno_ou_nulo():
    cmp = dict(BASE, **{"1.01.04": ("Adiantamentos", 900.0), "1.01.05": ("Tributos a Recuperar", None)})
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    assert _classes(flags) == {("1.01.04", "zero_padding"), ("1.01.05", "zero_padding")}
    f = [x for x in _linhas(flags) if x["cd_conta"] == "1.01.04"][0]
    assert (f["valor_ref"], f["valor_cmp"], f["severity"]) == (None, 900.0, "info")
    assert f["detalhe"] == {"exclusivo_em": "cmp"}


def test_tres_linhas_finas_viram_uma_outras():
    ref = dict(BASE, **{"1.01.04": ("Adiantamentos", 2e6), "1.01.05": ("Tributos", 3e6), "1.01.06": ("Despesas Antecipadas", 5e6)})
    ref["1.01"] = ("Ativo Circulante", 70e6); ref["1"] = ("Ativo Total", 110e6)
    cmp = dict(BASE, **{"1.01.09": ("Outras Contas", 10e6)})
    cmp["1.01"] = ("Ativo Circulante", 70e6); cmp["1"] = ("Ativo Total", 110e6)
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert {c for _, c in _classes(flags)} == {"reclassificado_em_outros"}
    assert {cd for cd, _ in _classes(flags)} == {"1.01.04", "1.01.05", "1.01.06", "1.01.09"}
    f = [x for x in _linhas(flags) if x["cd_conta"] == "1.01.04"][0]
    assert f["severity"] == "warn"
    assert f["detalhe"] == {"exclusivo_em": "ref", "soma_exclusivos_ref": 10e6, "soma_exclusivos_cmp": 0.0,
                            "outros_ref": 0.0, "outros_cmp": 10e6, "cd_outros_ref": [], "cd_outros_cmp": ["1.01.09"]}
    assert _resumo(flags)["classificacao"] == "reclassificado_em_outros" and _resumo(flags)["severity"] == "warn"


def test_outros_comum_absorve_linha_removida():
    ref = dict(BASE, **{"1.01.09": ("Outros", 1e6)}); ref["1.01"] = ("Ativo Circulante", 61e6)
    cmp = dict(BASE, **{"1.01.09": ("Outros", 11e6)}); cmp.pop("1.01.03"); cmp["1.01"] = ("Ativo Circulante", 61e6)
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert _classes(flags) == {("1.01.03", "reclassificado_em_outros")}


def test_renumerado_por_valor_sem_outros():
    ref = {"6.03": ("Financiamento", -100e6), "6.03.08": ("Dividendos Pagos", -100e6)}
    cmp = {"6.03": ("Financiamento", -100e6), "6.03.07": ("Dividendos pagos e a pagar", -100e6)}
    flags, _ = ccg.check_granularity(_df(_doc(ref, tipo_doc="DFC_MI", p_ini="2023-01-01"),
                                         _doc(cmp, "ITR", "2024-03-31", "Penúltimo", "2023-01-01", tipo_doc="DFC_MI")))
    assert _classes(flags) == {("6.03.08", "renumerado"), ("6.03.07", "renumerado")}
    f = [x for x in _linhas(flags) if x["cd_conta"] == "6.03.07"][0]
    assert f["detalhe"] == {"exclusivo_em": "cmp", "casamento": "valor", "cd_ref": ["6.03.08"], "cd_cmp": ["6.03.07"]}
    assert (f["valor_ref"], f["valor_cmp"]) == (None, -100e6)


def test_reclassificado_em_irmao_pai_inalterado():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.01"] = ("Caixa", 30e6)     # Estoques sumiu, Caixa absorveu; 1.01 = 60e6
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01.03", "reclassificado_em_irmao", "warn")
    assert f["detalhe"] == {"exclusivo_em": "ref", "soma_exclusivos_ref": 10e6, "soma_exclusivos_cmp": 0.0,
                            "pai_ref": 60e6, "pai_cmp": 60e6,
                            "irmaos_alterados": [{"cd": "1.01.01", "ref": 20e6, "cmp": 30e6}]}


def test_divergencia_nao_explicada_pai_mudou():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01"] = ("Ativo Circulante", 50e6); cmp["1"] = ("Ativo Total", 90e6)
    flags, stats = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01.03", "divergencia_nao_explicada", "error")
    assert f["detalhe"] == {"exclusivo_em": "ref", "soma_exclusivos_ref": 10e6, "soma_exclusivos_cmp": 0.0,
                            "pai_ref": 60e6, "pai_cmp": 50e6}
    assert _resumo(flags)["severity"] == "error"
    assert stats["BPA"]["divergencia_nao_explicada"] == 1


def test_raiz_sem_pai_vai_para_nao_explicada():
    ref = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6)}
    cmp = {"3.01": ("Receita", 100e6)}
    flags, _ = ccg.check_granularity(_df(_doc(ref, tipo_doc="DRE", p_ini="2023-01-01"),
                                         _doc(cmp, "ITR", "2024-03-31", "Penúltimo", "2023-01-01", tipo_doc="DRE")))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["cd_conta_pai"], f["classificacao"]) == ("3.02", "3", "divergencia_nao_explicada")
    assert f["detalhe"]["pai_ref"] is None and f["detalhe"]["pai_cmp"] is None


def test_opcoes_outorgadas_nao_e_outros():
    ref = dict(BASE, **{"1.01.09": ("Outros", 5e6)}); ref["1.01"] = ("Ativo Circulante", 65e6)
    cmp = dict(ref, **{"1.01.08": ("Opções Outorgadas", 2e6), "1.01.01": ("Caixa", 18e6)})   # 1.01 continua 65e6
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert _classes(flags) == {("1.01.08", "reclassificado_em_irmao")}


def test_filhos_de_pai_exclusivo_nao_geram_flag():
    cmp = dict(BASE, **{"1.02.05": ("Direito de Uso", 5e6), "1.02.05.01": ("Imóveis", 5e6), "1.02.01": ("Realizável LP", -5e6)})
    ref = dict(BASE, **{"1.02.01": ("Realizável LP", 0.0)})
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert _classes(flags) == {("1.02.05", "reclassificado_em_irmao")}
    assert _resumo(flags)["detalhe"]["filhos_de_pai_exclusivo"] == 1
    assert _resumo(flags)["detalhe"]["linhas_exclusivas_cmp"] == 2


def test_tolerancia_no_balanco():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("Inventário", 10e6 + 50e3)   # 0,5% < 1%
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    assert {c for _, c in _classes(flags)} == {"renumerado"}
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)), tol_rel=0.001)
    assert {c for _, c in _classes(flags)} == {"reclassificado_em_irmao"}     # 50e3 > 0,1%: não casa por valor; pai inalterado


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db_com_docs():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("ESTOQUES", 10e6)
    rows = _ref() + _cmp(cmp)
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
    monkeypatch.setattr(ccg, "get_db", lambda: conn)
    run1 = ccg.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT cd_conta, classificacao, severity FROM consistency_flags WHERE run_id = ? ORDER BY cd_conta",
                       (run1,)).fetchall()
    assert got == [(None, "renumerado", "info"), ("1.01.03", "renumerado", "info")]
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, finished_at "
                       "FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (3, "granularity", f"cnpj={CNPJ}", 1, 2) and run[5] is not None
    run2 = ccg.main(["--cnpj", CNPJ, "--tipo-doc", "BPA"])
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags").fetchone() == (2, 1)
    assert conn.execute("SELECT DISTINCT run_id FROM consistency_flags").fetchone()[0] == run2
    out = capsys.readouterr().out
    assert "BPA" in out and "pares=1" in out and "com_exclusivos=1" in out and "renumerado=1" in out


def test_main_full_e_exigencia_de_cnpj(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(ccg, "get_db", lambda: conn)
    run_id = ccg.main(["--full"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    import pytest
    with pytest.raises(SystemExit):
        ccg.main([])
