"""
Fase 1 da consistência financeira: helpers compartilhados (scripts/analysis/consistency_utils.py).
"""
import json
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import consistency_utils as cu

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _insert(conn, rows):
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    conn.commit()


def _row(**kw):
    base = {"cnpj_companhia": CNPJ, "fonte": "DFP", "tipo_doc": "BPA", "data_referencia": "2023-12-31",
            "versao": 1, "ordem_exercicio": "Último", "dt_ini_exerc": None, "dt_fim_exerc": "2023-12-31",
            "cd_conta": "1", "ds_conta": "Ativo Total", "vl_conta": 10.0, "st_conta_fixa": "S"}
    base.update(kw)
    return base


# ── tolerancia / parent_code / total_codes ───────────────────────────────────

def test_tolerancia_piso_absoluto_e_relativo():
    assert cu.tolerancia(0.0) == 1000.0
    assert cu.tolerancia(50_000.0) == 1000.0              # 1% = 500 < piso
    assert cu.tolerancia(1_000_000_000.0) == 10_000_000.0  # 1% de 1 bi
    assert cu.tolerancia(-1_000_000_000.0) == 10_000_000.0
    assert cu.tolerancia(100_000.0, tol_abs=10.0, tol_rel=0.005) == 500.0


def test_tolerancia_aceita_series():
    s = pd.Series([0.0, 1_000_000_000.0, -50_000.0])
    got = cu.tolerancia(s)
    assert list(got) == [1000.0, 10_000_000.0, 1000.0]


def test_parent_code():
    assert cu.parent_code("3.04.05.06") == "3.04.05"
    assert cu.parent_code("3.01") == "3"
    assert cu.parent_code("1") is None


def test_total_codes_fixos_por_tipo_doc():
    vazio = pd.DataFrame(columns=["cd_conta", "ds_conta"])
    assert cu.total_codes("BPA", vazio) == ["1"]
    assert cu.total_codes("BPP", vazio) == ["2"]
    assert cu.total_codes("DRE", vazio) == ["3.11", "3.01"]
    assert cu.total_codes("DFC_MI", vazio) == ["6.05"]


def test_total_codes_dva_resolve_pelo_nome():
    banco = pd.DataFrame([
        {"cd_conta": "7.07", "ds_conta": "Vlr Adicionado Recebido em Transferência"},
        {"cd_conta": "7.08", "ds_conta": "Valor Adicionado Total a Distribuir"},
        {"cd_conta": "7.08.01", "ds_conta": "Pessoal"},
        {"cd_conta": "7.06.03.02", "ds_conta": "Valor Adicionado Total a Distribuir"},  # nível 4: ignorar
    ])
    assert cu.total_codes("DVA", banco) == ["7.08"]
    sem_nome = pd.DataFrame([{"cd_conta": "7.07", "ds_conta": None}])
    assert cu.total_codes("DVA", sem_nome) == ["7.07"]


# ── parse_hierarchy / exceções / fórmulas (Fase 2) ───────────────────────────

def test_parse_hierarchy_filhos_diretos_por_pai_presente():
    arvore = cu.parse_hierarchy(["1", "1.01", "1.01.01", "1.01.02", "1.02"])
    assert arvore == {"1": ["1.01", "1.02"], "1.01": ["1.01.01", "1.01.02"]}


def test_parse_hierarchy_ignora_pai_ausente_e_duplicatas():
    # DRE não tem conta "3": 3.01 não tem pai no documento, mas 3.01.01 tem
    assert cu.parse_hierarchy(["3.01", "3.01.01", "3.01.01", "3.02"]) == {"3.01": ["3.01.01"]}
    assert cu.parse_hierarchy([]) == {}
    assert cu.parse_hierarchy(pd.Series(["2", "2.01"])) == {"2": ["2.01"]}


def test_excecoes_e_formulas_fixas():
    assert cu.EXCECOES_SOMA == {("DFC_MI", "6.05"): "saldo", ("DRE", "3.99"): "skip"}
    assert [alvo for alvo, _ in cu.FORMULAS_NIVEL2["DRE"]] == ["3.03", "3.05", "3.07", "3.09", "3.11"]
    assert cu.FORMULAS_NIVEL2["DFC_MI"] == [("6.05", ["6.01", "6.02", "6.03", "6.04"])]
    assert "BPA" not in cu.FORMULAS_NIVEL2


def test_cnpjs_financeiros():
    conn = _db()
    conn.executemany("INSERT INTO companies (cnpj, ticker, nome_cvm, setor) VALUES (?,?,?,?)", [
        (CNPJ, "WEGE3", "WEG", "Industrial"),
        ("60.746.948/0001-12", "BBDC4", "BRADESCO", "Financeiro"),
        ("00.000.000/0001-91", "BBAS3", "BB", "Financeiro"),
    ])
    assert cu.cnpjs_financeiros(conn) == {"60.746.948/0001-12", "00.000.000/0001-91"}


# ── normalize_text / is_outros (Fase 3) ──────────────────────────────────────

def test_normalize_text_acentos_caixa_pontuacao_e_nulos():
    assert cu.normalize_text("  Provisões p/ Contingências (Líquido)  ") == "provisoes p contingencias liquido"
    assert cu.normalize_text("CONTAS A RECEBER") == cu.normalize_text("Contas a receber")
    assert cu.normalize_text(None) == "" and cu.normalize_text(float("nan")) == ""


def test_is_outros_regex():
    assert cu.is_outros("Outros") and cu.is_outros("Outras Receitas Operacionais") and cu.is_outros("Demais contas")
    assert cu.is_outros("OUTRO ativo") and cu.is_outros("Outra Provisão")
    assert not cu.is_outros("Opções Outorgadas") and not cu.is_outros("Outorga de Concessão")
    assert not cu.is_outros(None)


def test_text_similarity_pares_conhecidos_e_reordenacao():
    assert abs(cu.text_similarity("Obrigações pós emprego", "Obrigação de benefício pós-emprego") - 0.75) < 0.01
    assert abs(cu.text_similarity("Partes relacionadas", "Fornecedores") - 0.19) < 0.01
    assert cu.text_similarity("Empréstimos e Financiamentos", "FINANCIAMENTOS E EMPRÉSTIMOS") == 1.0   # token-sort
    assert cu.text_similarity("Caixa", "Caixa") == 1.0 and cu.text_similarity("", "Caixa") == 0.0
    assert cu.text_similarity(None, None) == 0.0


# ── latest_rows ──────────────────────────────────────────────────────────────

def test_latest_rows_versao_maxima_por_documento_e_periodo_na():
    conn = _db()
    _insert(conn, [_row(versao=1, vl_conta=10.0), _row(versao=2, vl_conta=11.0),
                   _row(versao=2, cd_conta="1.01", ds_conta="Ativo Circulante", vl_conta=6.0)])
    df = cu.latest_rows(conn, cnpj=CNPJ)
    assert len(df) == 2
    assert set(df["versao"]) == {2}
    assert df.loc[df["cd_conta"] == "1", "vl_conta"].item() == 11.0
    assert set(df["periodo_ini"]) == {"NA"}
    assert set(df["periodo_fim"]) == {"2023-12-31"}


def test_latest_rows_filtros():
    conn = _db()
    _insert(conn, [
        _row(),
        _row(cnpj_companhia="00.000.000/0001-91"),
        _row(tipo_doc="DRE", dt_ini_exerc="2023-01-01"),
        _row(data_referencia="2021-12-31", dt_fim_exerc="2021-12-31"),
        _row(fonte="ITR", data_referencia="2024-03-31", ordem_exercicio="Penúltimo"),
    ])
    assert len(cu.latest_rows(conn)) == 5
    assert len(cu.latest_rows(conn, cnpj=CNPJ)) == 4
    assert len(cu.latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA")) == 3
    assert len(cu.latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA", desde=2023)) == 2
    assert len(cu.latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA", desde=2023, ate=2023)) == 1
    assert len(cu.latest_rows(conn, fonte="ITR")) == 1
    dre = cu.latest_rows(conn, tipo_doc="DRE")
    assert dre["periodo_ini"].item() == "2023-01-01"


def test_latest_rows_vazio_tem_colunas():
    df = cu.latest_rows(_db(), cnpj="nenhum")
    assert df.empty
    assert {"periodo_ini", "periodo_fim", "cd_conta", "vl_conta"} <= set(df.columns)


# ── runs / flags ─────────────────────────────────────────────────────────────

def test_new_run_finish_run_e_write_flags_roundtrip():
    conn = _db()
    run_id = cu.new_run(conn, layer=2, check_type="cross_period", escopo="cnpj=" + CNPJ,
                        script_args={"cnpj": CNPJ, "tol_abs": 1000.0})
    assert run_id.startswith("cross_period-")
    run = conn.execute("SELECT layer, check_type, escopo, started_at, finished_at, script_args "
                       "FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run[0] == 2 and run[1] == "cross_period" and run[2] == "cnpj=" + CNPJ
    assert run[3] is not None and run[4] is None
    assert json.loads(run[5]) == {"cnpj": CNPJ, "tol_abs": 1000.0}

    n = cu.write_flags(conn, run_id, [
        {"layer": 2, "check_type": "cross_period", "classificacao": "reapresentacao", "severity": "warn",
         "cnpj_companhia": CNPJ, "tipo_doc": "BPA", "cd_conta": "1", "cd_conta_pai": None,
         "ds_conta": "Ativo Total", "periodo_ini": "NA", "periodo_fim": "2023-12-31",
         "fonte_ref": "DFP", "data_ref": "2023-12-31", "ordem_ref": "Último",
         "fonte_cmp": "ITR", "data_cmp": "2024-03-31", "ordem_cmp": "Penúltimo",
         "valor_ref": 100.0, "valor_cmp": 110.0, "diff_abs": 10.0, "diff_rel": 0.1,
         "detalhe": {"linhas_divergentes": 1}},
        {"layer": 2, "check_type": "cross_period", "classificacao": "reclassificacao", "severity": "info",
         "cnpj_companhia": CNPJ, "tipo_doc": "BPA", "cd_conta": None,
         "valor_ref": float("nan"), "diff_rel": None},   # NaN vira NULL; chaves ausentes viram NULL
    ])
    assert n == 2
    assert cu.write_flags(conn, run_id, []) == 0
    got = conn.execute("SELECT cd_conta, valor_ref, diff_rel, detalhe, fonte_cmp FROM consistency_flags "
                       "WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    assert got[0] == ("1", 100.0, 0.1, '{"linhas_divergentes": 1}', "ITR")
    assert got[1] == (None, None, None, None, None)

    cu.finish_run(conn, run_id, total_checked=7, total_flagged=2)
    run = conn.execute("SELECT finished_at, total_checked, total_flagged FROM consistency_runs "
                       "WHERE run_id = ?", (run_id,)).fetchone()
    assert run[0] is not None and run[1] == 7 and run[2] == 2


def test_write_flags_rejeita_severity_invalida():
    conn = _db()
    run_id = cu.new_run(conn, 2, "cross_period", "x", {})
    with pytest.raises(sqlite3.IntegrityError):
        cu.write_flags(conn, run_id, [{"layer": 2, "check_type": "cross_period", "classificacao": "x",
                                       "severity": "fatal", "cnpj_companhia": CNPJ}])


def test_clear_flags_por_cnpj_e_tipo_doc():
    conn = _db()
    run_id = cu.new_run(conn, 2, "cross_period", "x", {})
    base = {"layer": 2, "check_type": "cross_period", "classificacao": "reclassificacao", "severity": "info"}
    cu.write_flags(conn, run_id, [
        {**base, "cnpj_companhia": CNPJ, "tipo_doc": "BPA"},
        {**base, "cnpj_companhia": CNPJ, "tipo_doc": "DRE"},
        {**base, "cnpj_companhia": "00.000.000/0001-91", "tipo_doc": "BPA"},
        {**base, "layer": 1, "check_type": "hierarchy", "cnpj_companhia": CNPJ, "tipo_doc": "BPA"},
    ])
    assert cu.clear_flags(conn, 2, "cross_period", CNPJ, tipo_doc="BPA") == 1
    assert cu.clear_flags(conn, 2, "cross_period", CNPJ) == 1          # sobrou a DRE
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 2


# ── add_common_args ──────────────────────────────────────────────────────────

def test_add_common_args_defaults_e_parse():
    import argparse
    p = argparse.ArgumentParser()
    cu.add_common_args(p)
    a = p.parse_args([])
    assert (a.cnpj, a.tipo_doc, a.desde, a.ate, a.full, a.tol_abs, a.tol_rel) == \
        (None, None, None, None, False, 1000.0, 0.01)
    a = p.parse_args(["--cnpj", CNPJ, "--tipo-doc", "DFC_MI", "--desde", "2020", "--ate", "2024",
                      "--tol-abs", "500", "--tol-rel", "0.02"])
    assert (a.cnpj, a.tipo_doc, a.desde, a.ate, a.tol_abs, a.tol_rel) == \
        (CNPJ, "DFC_MI", 2020, 2024, 500.0, 0.02)
    with pytest.raises(SystemExit):
        p.parse_args(["--tipo-doc", "XYZ"])


# ── polaridade contábil (entrada × saída) ────────────────────────────────────

def test_polaridade_classifica_entrada_saida_e_indefinido():
    assert cu.polaridade("Captação de debêntures") == "E"
    assert cu.polaridade("Emissão de ações") == "E"
    assert cu.polaridade("Pagamento de debêntures") == "S"
    assert cu.polaridade("Amortização de empréstimos") == "S"
    assert cu.polaridade("Recompra de ações") == "S"
    assert cu.polaridade("Lucro líquido do exercício") is None       # nenhum termo
    assert cu.polaridade("Aquisição e venda de imobilizado") is None  # os dois
    assert cu.polaridade(None) is None


def test_polaridade_conflita():
    # O caso real: a Multiplan não tinha 'Pagamento de debêntures' no ITR do 3T/2021,
    # e a similaridade de 0,756 casaria com 'Captação de debêntures'.
    assert cu.polaridade_conflita("Captação de debêntures", "Pagamento de debêntures")
    assert cu.polaridade_conflita("Aumento de capital social", "Redução de capital social")
    assert not cu.polaridade_conflita("Captação de debêntures", "Captação de debentures")
    assert not cu.polaridade_conflita("Pagamento de encargos e debêntures", "Pagamento de encargos sobre debêntures")
    assert not cu.polaridade_conflita("Lucro líquido", "Resultado líquido")           # sem polaridade
    assert not cu.polaridade_conflita("Aquisição e venda de bens", "Venda de bens")   # um lado indefinido
