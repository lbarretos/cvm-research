"""
Fase 5 da consistência financeira: Camada 6 (desacúmulo) + demonstrativos_trimestrais.
"""
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import derive_quarters as dq

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def test_schema_trimestrais():
    conn = _db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(demonstrativos_trimestrais)")]
    assert {"run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
            "cd_conta", "ds_conta", "cd_conta_b", "casamento", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
            "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"} <= set(cols)
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('r', 6, 'derive_quarters')")
    sql = ("INSERT INTO demonstrativos_trimestrais (run_id, cnpj_companhia, tipo_doc, safra, exercicio_ini, dt_ini_exerc, "
           "dt_fim_exerc, trimestre, cd_conta, origem, flag) VALUES ('r', ?, 'DRE', 'original', '2024-01-01', ?, ?, ?, '3.01', 'derivado', ?)")
    conn.execute(sql, (CNPJ, "2024-10-01", "2024-12-31", 4, "linha_sem_par"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2024-10-01", "2024-12-31", 4, None))          # UNIQUE (cnpj, tipo, safra, exercício, trimestre, conta)
    sql2 = sql.replace("'2024-01-01'", "'2024-04-01'")
    conn.execute(sql2, (CNPJ, "2024-10-01", "2024-12-31", 3, None))             # outro exercício, mesmo dt_fim: permitido
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2025-01-01", "2025-03-31", 5, None))          # trimestre 1..4
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2025-01-01", "2025-03-31", 1, "inventada"))   # CHECK flag
    conn.execute(sql.replace("'3.01'", "'3.02'"), (CNPJ, "2024-10-01", "2024-12-31", 4, "par_ambiguo"))
    conn.execute(sql.replace("'3.01'", "'3.04'"), (CNPJ, "2024-10-01", "2024-12-31", 4, "reclassificacao_entre_filings"))
    sql_cas = ("INSERT INTO demonstrativos_trimestrais (run_id, cnpj_companhia, tipo_doc, safra, exercicio_ini, dt_ini_exerc, "
               "dt_fim_exerc, trimestre, cd_conta, origem, casamento) VALUES ('r', ?, 'DRE', 'original', '2024-01-01', ?, ?, ?, ?, 'derivado', ?)")
    conn.execute(sql_cas, (CNPJ, "2024-10-01", "2024-12-31", 4, "3.03", "reformulacao"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql_cas, (CNPJ, "2024-10-01", "2024-12-31", 4, "3.04", "inventado"))   # CHECK casamento


def test_calendario():
    assert dq.meses("2024-01-01", "2024-03-31") == 3 and dq.meses("2024-01-01", "2024-12-31") == 12
    assert dq.meses("2023-04-01", "2024-03-31") == 12 and dq.meses("2024-01-01", "2024-01-31") == 1
    assert dq.trimestre_de("2024-01-01", "2024-06-30") == 2 and dq.trimestre_de("2023-04-01", "2023-06-30") == 1
    assert dq.trimestre_de("2024-01-01", "2024-01-31") is None and dq.trimestre_de("2023-01-01", "2024-01-31") is None
    assert dq.inicio_trimestre("2024-01-01", 1) == "2024-01-01" and dq.inicio_trimestre("2024-01-01", 4) == "2024-10-01"
    assert dq.inicio_trimestre("2023-04-01", 4) == "2024-01-01"


# ── lógica pura ──────────────────────────────────────────────────────────────

def _doc(fonte, data_ref, ordem, ini, fim, contas, tipo_doc="DRE", tri=None, st="S"):
    """Linhas de um documento: acumulado (ini..fim) e, se tri, a linha trimestral isolada (tri_ini..fim).
    st = st_conta_fixa das linhas ('N' = conta criada pela empresa, sujeita a renumeração)."""
    rows = [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref, "versao": 1,
             "ordem_exercicio": ordem, "periodo_ini": ini, "periodo_fim": fim, "cd_conta": cd, "ds_conta": ds,
             "vl_conta": vl, "st_conta_fixa": st} for cd, (ds, vl) in contas.items()]
    if tri:
        tri_ini, tri_contas = tri
        rows += [dict(r, periodo_ini=tri_ini, vl_conta=tri_contas[r["cd_conta"]]) for r in rows if r["cd_conta"] in tri_contas]
    return rows


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


R = lambda v: {"3.01": ("Receita", v), "3.11": ("Lucro", v / 10)}
ANO24 = [
    _doc("ITR", "2024-03-31", "Último", "2024-01-01", "2024-03-31", R(100e6)),
    _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", R(230e6), tri=("2024-04-01", {"3.01": 130e6, "3.11": 13e6})),
    _doc("ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30", R(360e6), tri=("2024-07-01", {"3.01": 130e6, "3.11": 13e6})),
    _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", R(500e6)),
]


def _linhas(rows, cd="3.01"):
    return {r["trimestre"]: r for r in rows if r["cd_conta"] == cd}


def test_dre_publicado_nos_tres_primeiros_e_4t_derivado():
    rows, flags, stats = dq.derive_quarters(_df(*ANO24))
    q = _linhas(rows)
    assert [(n, q[n]["vl_publicado"], q[n]["vl_derivado"], q[n]["origem"], q[n]["vl_final"], q[n]["flag"]) for n in (1, 2, 3, 4)] == [
        (1, 100e6, 100e6, "publicado", 100e6, None),
        (2, 130e6, 130e6, "publicado", 130e6, None),
        (3, 130e6, 130e6, "publicado", 130e6, None),
        (4, None, 140e6, "derivado", 140e6, None),
    ]
    r = q[4]
    assert (r["cnpj_companhia"], r["tipo_doc"], r["safra"], r["exercicio_ini"], r["dt_ini_exerc"], r["dt_fim_exerc"]) == \
        (CNPJ, "DRE", "original", "2024-01-01", "2024-10-01", "2024-12-31")
    assert (r["fonte_a"], r["data_a"], r["ordem_a"], r["fonte_b"], r["data_b"], r["ordem_b"]) == \
        ("DFP", "2024-12-31", "Último", "ITR", "2024-09-30", "Último")
    assert (q[1]["fonte_b"], q[1]["data_b"]) == (None, None) and q[1]["ds_conta"] == "Receita"
    assert q[2]["dt_ini_exerc"] == "2024-04-01" and q[2]["dt_fim_exerc"] == "2024-06-30"
    assert len(rows) == 8 and flags == []
    assert stats["DRE"] == {"exercicios": 1, "trimestres": 4, "linhas": 8, "docs_irregulares": 0,
                            "reapresentacao_intra_ano": 0, "reclassificacao_entre_filings": 0,
                            "componente_reapresentado": 0, "linha_sem_par": 0,
                            "par_ambiguo": 0, "sem_anterior": 0, "sem_3t": 0, "sem_dfp": 0}


def test_publicado_diferente_do_derivado_gera_flag_e_mantem_publicado():
    docs = [d.copy() for d in ANO24]
    docs[1] = _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", R(230e6), tri=("2024-04-01", {"3.01": 125e6, "3.11": 13e6}))
    rows, flags, stats = dq.derive_quarters(_df(*docs))
    r = _linhas(rows)[2]
    assert (r["vl_publicado"], r["vl_derivado"], r["vl_final"], r["flag"]) == (125e6, 130e6, 125e6, "reapresentacao_intra_ano")
    f, = flags
    assert (f["layer"], f["check_type"], f["classificacao"], f["severity"], f["cd_conta"], f["tipo_doc"]) == \
        (6, "derive_quarters", "reapresentacao_intra_ano", "warn", "3.01", "DRE")
    assert (f["periodo_ini"], f["periodo_fim"], f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == ("2024-04-01", "2024-06-30", 125e6, 130e6, 5e6)
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("ITR", "2024-06-30", "ITR", "2024-03-31")
    assert f["detalhe"] == {"safra": "original", "trimestre": 2, "exercicio_ini": "2024-01-01"}
    assert stats["DRE"]["reapresentacao_intra_ano"] == 1


def test_dfc_so_derivado_e_checagem_de_caixa_no_4t():
    D = lambda op, ini, fim: {"6.01": ("Operacional", op), "6.05": ("Variação de caixa", fim - ini),
                              "6.05.01": ("Saldo inicial", ini), "6.05.02": ("Saldo final", fim)}
    docs = [_doc("ITR", "2024-03-31", "Último", "2024-01-01", "2024-03-31", D(10e6, 50e6, 60e6), "DFC_MI"),
            _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", D(25e6, 50e6, 75e6), "DFC_MI"),
            _doc("ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30", D(40e6, 50e6, 90e6), "DFC_MI"),
            _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", D(60e6, 50e6, 110e6), "DFC_MI")]
    rows, flags, _ = dq.derive_quarters(_df(*docs))
    q = _linhas(rows, "6.01")
    assert [(q[n]["vl_publicado"], q[n]["vl_derivado"], q[n]["origem"], q[n]["vl_final"]) for n in (1, 2, 3, 4)] == \
        [(None, 10e6, "derivado", 10e6), (None, 15e6, "derivado", 15e6), (None, 15e6, "derivado", 15e6), (None, 20e6, "derivado", 20e6)]
    assert _linhas(rows, "6.05")[4]["flag"] is None and flags == []
    docs[3] = _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", D(60e6, 45e6, 110e6), "DFC_MI")   # saldo inicial reapresentado
    rows, flags, _ = dq.derive_quarters(_df(*docs))
    r = _linhas(rows, "6.05")[4]
    assert (r["vl_derivado"], r["flag"]) == (25e6, "reapresentacao_intra_ano")       # 65 − 40 = 25 ≠ 110 − 90 = 20
    f, = flags
    assert (f["cd_conta"], f["valor_ref"], f["valor_cmp"]) == ("6.05", 25e6, 20e6) and f["detalhe"]["verificacao"] == "saldo_final"


def test_dfc_4t_usa_bpa_quando_nao_ha_saldo_final_so_na_safra_original():
    D = lambda op: {"6.01": ("Operacional", op), "6.05": ("Variação de caixa", op)}
    B = lambda cx, fim, ordem="Último", data=None: [{"cnpj_companhia": CNPJ, "fonte": "DFP" if fim.endswith("12-31") else "ITR",
        "tipo_doc": "BPA", "data_referencia": data or fim, "versao": 1, "ordem_exercicio": ordem, "periodo_ini": "NA", "periodo_fim": fim,
        "cd_conta": "1.01.01", "ds_conta": "Caixa", "vl_conta": cx, "st_conta_fixa": "S"}]
    docs = [_doc("ITR", "2024-03-31", "Último", "2024-01-01", "2024-03-31", D(10e6), "DFC_MI"),
            _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", D(25e6), "DFC_MI"),
            _doc("ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30", D(40e6), "DFC_MI"),
            _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", D(60e6), "DFC_MI")]
    rows, flags, _ = dq.derive_quarters(_df(*docs, B(90e6, "2024-09-30"), B(110e6, "2024-12-31")))
    assert _linhas(rows, "6.05")[4]["flag"] is None                                  # 20 = 110 − 90
    rows, flags, _ = dq.derive_quarters(_df(*docs, B(90e6, "2024-09-30"), B(115e6, "2024-12-31")))
    assert _linhas(rows, "6.05")[4]["flag"] == "reapresentacao_intra_ano" and flags[0]["detalhe"]["verificacao"] == "bpa_caixa"
    rows, flags, _ = dq.derive_quarters(_df(*docs))                                 # sem BPA: sem checagem
    assert _linhas(rows, "6.05")[4]["flag"] is None and flags == []


def test_safra_reapresentada_usa_so_penultimo():
    pen = [_doc("ITR", "2025-03-31", "Penúltimo", "2024-01-01", "2024-03-31", R(101e6)),
           _doc("ITR", "2025-06-30", "Penúltimo", "2024-01-01", "2024-06-30", R(231e6), tri=("2024-04-01", {"3.01": 130e6, "3.11": 13e6})),
           _doc("ITR", "2025-09-30", "Penúltimo", "2024-01-01", "2024-09-30", R(361e6), tri=("2024-07-01", {"3.01": 130e6, "3.11": 13e6})),
           _doc("DFP", "2025-12-31", "Penúltimo", "2024-01-01", "2024-12-31", R(510e6))]
    rows, _, stats = dq.derive_quarters(_df(*ANO24, *pen))
    orig = {r["trimestre"]: r for r in rows if r["cd_conta"] == "3.01" and r["safra"] == "original"}
    reap = {r["trimestre"]: r for r in rows if r["cd_conta"] == "3.01" and r["safra"] == "reapresentado"}
    assert (orig[4]["vl_derivado"], reap[4]["vl_derivado"]) == (140e6, 149e6)          # nunca mistura safras
    assert (reap[1]["vl_final"], reap[2]["vl_final"], reap[2]["vl_derivado"]) == (101e6, 130e6, 130e6)
    assert (reap[4]["fonte_a"], reap[4]["data_a"], reap[4]["ordem_a"], reap[4]["data_b"], reap[4]["ordem_b"]) == \
        ("DFP", "2025-12-31", "Penúltimo", "2025-09-30", "Penúltimo")
    assert stats["DRE"]["exercicios"] == 2 and stats["DRE"]["trimestres"] == 8


def test_exercicio_social_comecando_em_abril():
    docs = [_doc("ITR", "2023-06-30", "Último", "2023-04-01", "2023-06-30", R(100e6)),
            _doc("ITR", "2023-09-30", "Último", "2023-04-01", "2023-09-30", R(230e6), tri=("2023-07-01", {"3.01": 130e6, "3.11": 13e6})),
            _doc("ITR", "2023-12-31", "Último", "2023-04-01", "2023-12-31", R(360e6), tri=("2023-10-01", {"3.01": 130e6, "3.11": 13e6})),
            _doc("DFP", "2024-03-31", "Último", "2023-04-01", "2024-03-31", R(500e6))]
    rows, _, _ = dq.derive_quarters(_df(*docs))
    q = _linhas(rows)
    assert [(n, q[n]["dt_ini_exerc"], q[n]["dt_fim_exerc"]) for n in (1, 2, 3, 4)] == [
        (1, "2023-04-01", "2023-06-30"), (2, "2023-07-01", "2023-09-30"), (3, "2023-10-01", "2023-12-31"), (4, "2024-01-01", "2024-03-31")]
    assert q[4]["vl_derivado"] == 140e6 and {r["exercicio_ini"] for r in rows} == {"2023-04-01"}


def test_linha_sem_par_e_lucro_por_acao_ignorado():
    docs = [d.copy() for d in ANO24]
    docs[3] = _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31",
                   dict(R(500e6), **{"3.04": ("Despesas", -50e6), "3.99": ("LPA", 1.2), "3.99.01": ("Básico", 1.2)}))
    rows, flags, stats = dq.derive_quarters(_df(*docs))
    r = [x for x in rows if x["cd_conta"] == "3.04"][0]
    assert (r["trimestre"], r["vl_derivado"], r["vl_final"], r["origem"], r["flag"]) == (4, None, None, "derivado", "linha_sem_par")
    assert not [x for x in rows if x["cd_conta"].startswith("3.99")]
    assert flags == [] and stats["DRE"]["linha_sem_par"] == 1


def test_buracos_sem_anterior_sem_3t_sem_dfp():
    docs = [ANO24[0], ANO24[2], ANO24[3]]                                          # sem 2T
    rows, flags, stats = dq.derive_quarters(_df(*docs))
    q = _linhas(rows)
    assert (q[3]["vl_publicado"], q[3]["vl_derivado"], q[3]["vl_final"], q[3]["flag"]) == (130e6, None, 130e6, "sem_anterior")
    assert q[4]["vl_derivado"] == 140e6 and q[4]["flag"] is None
    f, = flags
    assert (f["classificacao"], f["severity"], f["cd_conta"], f["periodo_ini"], f["periodo_fim"]) == ("sem_anterior", "info", None, "2024-07-01", "2024-09-30")
    assert f["detalhe"] == {"safra": "original", "trimestre": 3, "exercicio_ini": "2024-01-01", "linhas": 2}
    rows, flags, stats = dq.derive_quarters(_df(ANO24[0], ANO24[1], ANO24[3]))     # sem 3T
    q = _linhas(rows)
    assert (q[4]["vl_derivado"], q[4]["vl_final"], q[4]["flag"]) == (None, None, "sem_3t") and flags[0]["classificacao"] == "sem_3t"
    rows, flags, stats = dq.derive_quarters(_df(*ANO24[:3]))                        # sem DFP
    assert 4 not in _linhas(rows) and [f["classificacao"] for f in flags] == ["sem_dfp"]
    assert (flags[0]["periodo_ini"], flags[0]["periodo_fim"], flags[0]["cd_conta"]) == ("2024-01-01", "2024-09-30", None)
    assert stats["DRE"]["sem_dfp"] == 1


def test_componente_reapresentado_pela_camada2():
    reap = {("DRE", "DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31")}
    rows, flags, stats = dq.derive_quarters(_df(*ANO24), reapresentados=reap)
    q = _linhas(rows)
    assert q[4]["flag"] == "componente_reapresentado" and q[3]["flag"] is None
    f, = flags
    assert (f["classificacao"], f["severity"], f["cd_conta"], f["detalhe"]["linhas"]) == ("componente_reapresentado", "info", None, 2)
    assert stats["DRE"]["componente_reapresentado"] == 2


def test_documento_irregular_e_dataframe_vazio():
    docs = [*ANO24, _doc("ITR", "2025-01-31", "Último", "2025-01-01", "2025-01-31", R(30e6)),
            _doc("DFP", "2025-06-30", "Último", "2025-01-01", "2025-06-30", R(200e6))]
    rows, _, stats = dq.derive_quarters(_df(*docs))
    assert {r["exercicio_ini"] for r in rows} == {"2024-01-01"} and stats["DRE"]["docs_irregulares"] == 2
    assert dq.derive_quarters(pd.DataFrame()) == ([], [], {})


# ── casamento de linhas entre os dois acumulados ─────────────────────────────

# Multiplan, DFC, 2026: a empresa reordena os códigos do bloco 6.03 entre o 1T e o 2T.
MULT_1T = {"6.03": ("Caixa Líquido Atividades de Financiamento", -317.0e6),
           "6.03.06": ("Pagamento de encargos e debêntures", -144.9e6),
           "6.03.08": ("Dividendos e juros sobre capital próprio", -97.5e6)}
MULT_2T = {"6.03": ("Caixa Líquido Atividades de Financiamento", -967.3e6),
           "6.03.06": ("Pagamento de debêntures", -175.0e6),
           "6.03.08": ("Pagamento de encargos sobre debêntures", -347.0e6),
           "6.03.09": ("Dividendos e juros sobre o capital prórpio", -203.4e6)}


def _mult(contas_1t=None, contas_2t=None):
    return _df(_doc("ITR", "2026-03-31", "Último", "2026-01-01", "2026-03-31", contas_1t or MULT_1T, "DFC_MI", st="N"),
               _doc("ITR", "2026-06-30", "Último", "2026-01-01", "2026-06-30", contas_2t or MULT_2T, "DFC_MI", st="N"))


def test_renumeracao_nao_mistura_encargos_de_debentures_com_dividendos():
    rows, flags, stats = dq.derive_quarters(_mult())
    q2 = {r["cd_conta"]: r for r in rows if r["trimestre"] == 2}
    # 6.03.08 no 2T é a linha que era 6.03.06 no 1T: −347,0 − (−144,9)
    r = q2["6.03.08"]
    assert (round(r["vl_derivado"] / 1e6, 1), r["cd_conta_b"], r["casamento"], r["flag"]) == (-202.1, "6.03.06", "reformulacao", None)
    # 6.03.09 no 2T é a linha que era 6.03.08 no 1T: −203,4 − (−97,5)
    r = q2["6.03.09"]
    assert (round(r["vl_derivado"] / 1e6, 1), r["cd_conta_b"], r["casamento"], r["flag"]) == (-105.9, "6.03.08", "reformulacao", None)
    # 6.03.06 no 2T ("Pagamento de debêntures") é linha nova: não deriva contra os encargos do 1T
    r = q2["6.03.06"]
    assert (r["vl_derivado"], r["vl_final"], r["cd_conta_b"], r["casamento"], r["flag"]) == (None, None, None, None, "linha_sem_par")
    assert stats["DFC_MI"]["linha_sem_par"] == 1 and stats["DFC_MI"]["par_ambiguo"] == 0


def test_par_ambiguo_nao_deriva_e_vira_fila_de_revisao():
    rows, flags, _ = dq.derive_quarters(_mult({"6.03": ("Financiamento", 100e6), "6.03.09": ("Captação de debêntures", 482.8e6)},
                                              {"6.03": ("Financiamento", 100e6), "6.03.12": ("Emissão de debêntures", 482.8e6)}))
    r = {x["cd_conta"]: x for x in rows if x["trimestre"] == 2}["6.03.12"]
    assert (r["vl_derivado"], r["vl_final"], r["origem"]) == (None, None, "derivado")
    assert (r["cd_conta_b"], r["casamento"], r["flag"]) == ("6.03.09", "ambiguo", "par_ambiguo")
    f, = [x for x in flags if x["classificacao"] == "par_ambiguo"]
    assert (f["layer"], f["check_type"], f["severity"], f["tipo_doc"], f["cd_conta"]) == (6, "derive_quarters", "warn", "DFC_MI", "6.03.12")
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("ITR", "2026-06-30", "ITR", "2026-03-31")
    assert (f["valor_ref"], f["valor_cmp"]) == (482.8e6, 482.8e6)
    assert (f["detalhe"]["cd_conta_b"], f["detalhe"]["ds_conta_b"]) == ("6.03.09", "Captação de debêntures")
    assert 0.55 < f["detalhe"]["score"] < 0.75


def test_mesmo_codigo_com_texto_retocado_continua_derivando():
    r = {x["cd_conta"]: x for x in dq.derive_quarters(_mult(
        {"6.03": ("Financiamento", 10e6), "6.03.01": ("Pagamento de emprestimos", 30e6)},
        {"6.03": ("Financiamento", 25e6), "6.03.01": ("Pagamento de empréstimos", 50e6)}))[0] if x["trimestre"] == 2}
    assert (r["6.03.01"]["vl_derivado"], r["6.03.01"]["cd_conta_b"], r["6.03.01"]["casamento"]) == (20e6, "6.03.01", "estavel")


def test_4t_casa_o_layout_do_dfp_com_o_do_itr_do_3t():
    itr3 = {"6.03": ("Financiamento", -430.0e6), "6.03.06": ("Dividendos e juros sobre o capital próprio pagos", -316.4e6),
            "6.03.07": ("Gastos com operações de ações", -0.1e6), "6.03.08": ("Pagamento de encargos sobre debêntures", -352.5e6)}
    dfp = {"6.03": ("Financiamento", -860.9e6), "6.03.07": ("Pagamento de encargos sobre debêntures", -560.1e6),
           "6.03.08": ("Aumento de capital social", 0.0), "6.03.09": ("Gastos com operações de ações", -0.1e6),
           "6.03.11": ("Dividendos pagos e juros sobre capital próprio", -492.0e6)}
    rows, _, _ = dq.derive_quarters(_df(
        _doc("ITR", "2025-03-31", "Último", "2025-01-01", "2025-03-31", {"6.03": ("Financiamento", -100e6)}, "DFC_MI", st="N"),
        _doc("ITR", "2025-06-30", "Último", "2025-01-01", "2025-06-30", {"6.03": ("Financiamento", -200e6)}, "DFC_MI", st="N"),
        _doc("ITR", "2025-09-30", "Último", "2025-01-01", "2025-09-30", itr3, "DFC_MI", st="N"),
        _doc("DFP", "2025-12-31", "Último", "2025-01-01", "2025-12-31", dfp, "DFC_MI", st="N")))
    q4 = {r["cd_conta"]: r for r in rows if r["trimestre"] == 4}
    assert (round(q4["6.03.07"]["vl_derivado"] / 1e6, 1), q4["6.03.07"]["cd_conta_b"]) == (-207.6, "6.03.08")
    assert (round(q4["6.03.11"]["vl_derivado"] / 1e6, 1), q4["6.03.11"]["cd_conta_b"]) == (-175.6, "6.03.06")
    assert (q4["6.03.09"]["vl_derivado"], q4["6.03.09"]["cd_conta_b"]) == (0.0, "6.03.07")
    # "Aumento de capital social" não existe no ITR do 3T: não pode virar o 4T dos encargos
    assert (q4["6.03.08"]["vl_derivado"], q4["6.03.08"]["flag"]) == (None, "linha_sem_par")


def test_primeiro_trimestre_nao_tem_casamento():
    r = {x["cd_conta"]: x for x in dq.derive_quarters(_mult())[0] if x["trimestre"] == 1}["6.03.08"]
    assert (r["cd_conta_b"], r["casamento"], r["vl_derivado"]) == (None, None, -97.5e6)


# ── layouts diferentes entre minuendo e subtraendo (Camada 2 'reclassificacao') ──

def _v(d03, d04, d02):
    """Bloco 3.04 da DRE (valores em R$ bi). Vale 2024: o ITR 3T24 põe o ganho de 11,756 bi em
    3.04.04; o DFP 2024 e os filings de 2025 já usam o layout novo, com ele em 3.04.03."""
    return {"3.04": ("Despesas/Receitas Operacionais", (d02 + d03 + d04) * 1e9),
            "3.04.02": ("Despesas Gerais e Administrativas", d02 * 1e9),
            "3.04.03": ("Perdas pela Não Recuperabilidade de Ativos", d03 * 1e9),
            "3.04.04": ("Outras Receitas Operacionais", d04 * 1e9)}


def _exercicio(ano, ordem, data_ano, blocos):
    """Os quatro acumulados de `ano` publicados nos filings de `data_ano` (Último: data_ano = ano)."""
    fins = ["03-31", "06-30", "09-30", "12-31"]
    return [_doc("DFP" if n == 3 else "ITR", f"{data_ano}-{fins[n]}", ordem, f"{ano}-01-01", f"{ano}-{fins[n]}", blocos[n])
            for n in range(4)]


VALE24 = _exercicio(2024, "Último", 2024, [_v(0, 0, -0.2), _v(0, 0, -0.4), _v(0, 11.756, -0.6), _v(0.51, 0, -0.8)])
VALE24_REAP = _exercicio(2024, "Penúltimo", 2025, [_v(0, 0, -0.2), _v(0, 0, -0.4), _v(11.756, 0, -0.6), _v(0.51, 0, -0.8)])


def _div(pares):
    """Saída de divergencias_camada2 a partir de flags de linha da Camada 2:
    pares = [(ref, cmp, periodo_ini, periodo_fim, classificacao, {cd: (valor_ref, valor_cmp)})],
    ref/cmp = (fonte, data, ordem)."""
    out = {}
    for ref, cmp, pi, pf, classe, linhas in pares:
        for cd, (vr, vc) in linhas.items():
            out.setdefault(("DRE", *ref, pi, pf), {})[cd] = (vc - vr, classe)
            out.setdefault(("DRE", *cmp, pi, pf), {})[cd] = (vr - vc, classe)
    return out


# Camada 2 do 9M24: ITR 3T24 (Último) × ITR 3T25 (Penúltimo) — 11,756 bi saem de 3.04.04 e vão para 3.04.03
DIV_9M24 = (("ITR", "2024-09-30", "Último"), ("ITR", "2025-09-30", "Penúltimo"), "2024-01-01", "2024-09-30",
            "reclassificacao", {"3.04.03": (0.0, 11.756e9), "3.04.04": (11.756e9, 0.0)})


def _q4(rows, safra, ano=2024):
    return {r["cd_conta"]: r for r in rows if r["safra"] == safra and r["trimestre"] == 4 and r["exercicio_ini"] == f"{ano}-01-01"}


def test_reclassificacao_entre_filings_vale_4t24():
    rows, flags, stats = dq.derive_quarters(_df(*VALE24, *VALE24_REAP), divergencias=_div([DIV_9M24]))
    orig, reap = _q4(rows, "original"), _q4(rows, "reapresentado")
    # original: DFP 2024 (layout novo) − ITR 3T24 (layout antigo) — linha a linha distorcido, com flag
    assert (round(orig["3.04.04"]["vl_final"] / 1e9, 3), orig["3.04.04"]["casamento"], orig["3.04.04"]["flag"]) == \
        (-11.756, "estavel", "reclassificacao_entre_filings")
    assert (round(orig["3.04.03"]["vl_final"] / 1e9, 3), orig["3.04.03"]["flag"]) == (0.51, "reclassificacao_entre_filings")
    # o total e a linha que não mudou de layout seguem sem flag
    assert (orig["3.04"]["flag"], round(orig["3.04.02"]["vl_final"] / 1e9, 3), orig["3.04.02"]["flag"]) == (None, -0.2, None)
    # reapresentado: DFP 2025 e ITR 3T25 no mesmo layout — o 4T certo, sem flag
    assert (round(reap["3.04.03"]["vl_final"] / 1e9, 3), reap["3.04.03"]["flag"]) == (-11.246, None)
    assert (reap["3.04.04"]["vl_final"], reap["3.04.04"]["flag"]) == (0.0, None)
    f, = [x for x in flags if x["classificacao"] == "reclassificacao_entre_filings"]
    assert (f["layer"], f["severity"], f["cd_conta"], f["periodo_ini"], f["periodo_fim"]) == (6, "warn", None, "2024-10-01", "2024-12-31")
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("DFP", "2024-12-31", "ITR", "2024-09-30")
    assert f["detalhe"] == {"safra": "original", "trimestre": 4, "exercicio_ini": "2024-01-01", "linhas": 2}
    assert stats["DRE"]["reclassificacao_entre_filings"] == 2


def test_reclassificacao_propaga_para_a_safra_reapresentada_do_ano_anterior():
    """O DFP 2024 e o ITR 3T24 também trazem o 12M23 e o 9M23 (Penúltimo): o 4T23 reapresentado
    subtrai os mesmos dois documentos, em layouts diferentes. O 4T23 original (DFP 2023 − ITR 3T23,
    os dois no layout antigo) está certo."""
    ano23 = _exercicio(2023, "Último", 2023, [_v(0, 0, -0.2), _v(0, 0, -0.4), _v(0, 2, -0.6), _v(0, 3, -0.8)])
    ano23_reap = _exercicio(2023, "Penúltimo", 2024, [_v(0, 0, -0.2), _v(0, 0, -0.4), _v(0, 2, -0.6), _v(3, 0, -0.8)])
    div_12m23 = (("DFP", "2023-12-31", "Último"), ("DFP", "2024-12-31", "Penúltimo"), "2023-01-01", "2023-12-31",
                 "reclassificacao", {"3.04.03": (0.0, 3e9), "3.04.04": (3e9, 0.0)})
    rows, _, _ = dq.derive_quarters(_df(*ano23, *ano23_reap, *VALE24, *VALE24_REAP), divergencias=_div([DIV_9M24, div_12m23]))
    orig23, reap23 = _q4(rows, "original", 2023), _q4(rows, "reapresentado", 2023)
    assert (orig23["3.04.04"]["vl_final"], orig23["3.04.04"]["flag"]) == (1e9, None)
    assert (reap23["3.04.03"]["vl_final"], reap23["3.04.03"]["flag"]) == (3e9, "reclassificacao_entre_filings")
    assert (reap23["3.04.04"]["vl_final"], reap23["3.04.04"]["flag"]) == (-2e9, "reclassificacao_entre_filings")
    assert reap23["3.04.02"]["flag"] is None
    # sem a marcação do par de documentos na safra original de 2024, não há evidência para o 4T23
    rows, _, _ = dq.derive_quarters(_df(*ano23, *ano23_reap), divergencias=_div([div_12m23]))
    assert {r["flag"] for r in _q4(rows, "reapresentado", 2023).values()} == {None}


def test_sem_flag_quando_os_dois_filings_mudaram_ou_nao_ha_versao_posterior():
    # layout trocado depois dos dois: o DFP 2024 também tinha o ganho em 3.04.04 e também diverge
    antigo = _exercicio(2024, "Último", 2024, [_v(0, 0, -0.2), _v(0, 0, -0.4), _v(0, 11.756, -0.6), _v(-11.246, 11.756, -0.8)])
    div_12m = (("DFP", "2024-12-31", "Último"), ("DFP", "2025-12-31", "Penúltimo"), "2024-01-01", "2024-12-31",
               "reclassificacao", {"3.04.03": (-11.246e9, 0.51e9), "3.04.04": (11.756e9, 0.0)})
    rows, _, _ = dq.derive_quarters(_df(*antigo, *VALE24_REAP), divergencias=_div([DIV_9M24, div_12m]))
    assert {r["flag"] for r in _q4(rows, "original").values()} == {None}
    # sem o DFP 2025 não se sabe em que layout o DFP 2024 está
    rows, _, _ = dq.derive_quarters(_df(*VALE24, *VALE24_REAP[:3]), divergencias=_div([DIV_9M24]))
    assert {r["flag"] for r in _q4(rows, "original").values()} == {None}
    # divergência classificada como reapresentacao (valor mudou, não só de linha) não é evidência de layout
    reap = (*DIV_9M24[:4], "reapresentacao", DIV_9M24[5])
    rows, _, _ = dq.derive_quarters(_df(*VALE24, *VALE24_REAP), divergencias=_div([reap]))
    assert {r["flag"] for r in _q4(rows, "original").values()} == {None}


def test_renumeracao_na_versao_posterior_nao_e_reclassificacao():
    """A Camada 2 compara por código: uma linha inserida no ITR 3T25 desloca 3.04.04 para 3.04.05 e
    aparece como 'reclassificacao', mas o conteúdo não mudou de linha (o nome em 3.04.04 mudou)."""
    reap_3t = {**_v(0, 0, -0.6), "3.04.04": ("Resultado na alienação de participação", 0.0),
               "3.04.05": ("Outras Receitas Operacionais", 11.756e9)}
    reap = [*VALE24_REAP[:2], _doc("ITR", "2025-09-30", "Penúltimo", "2024-01-01", "2024-09-30", reap_3t), VALE24_REAP[3]]
    div = (*DIV_9M24[:5], {"3.04.04": (11.756e9, 0.0), "3.04.05": (0.0, 11.756e9)})
    rows, _, _ = dq.derive_quarters(_df(*VALE24, *reap), divergencias=_div([div]))
    assert _q4(rows, "original")["3.04.04"]["flag"] is None


def test_divergencias_camada2_le_os_dois_lados_com_sinal():
    conn = _db()
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('l2', 2, 'cross_period')")
    sql = """INSERT INTO consistency_flags (run_id, layer, check_type, classificacao, severity, cnpj_companhia, tipo_doc,
        cd_conta, periodo_ini, periodo_fim, fonte_ref, data_ref, ordem_ref, fonte_cmp, data_cmp, ordem_cmp, valor_ref, valor_cmp, diff_abs)
        VALUES ('l2', 2, 'cross_period', ?, 'info', ?, 'DRE', ?, '2024-01-01', '2024-09-30',
        'ITR', '2024-09-30', 'Último', 'ITR', '2025-09-30', 'Penúltimo', ?, ?, ?)"""
    conn.execute(sql, ("reclassificacao", CNPJ, "3.04.04", 11.756e9, 0.0, -11.756e9))
    conn.execute(sql, ("reclassificacao", CNPJ, None, None, None, None))           # resumo do par: fora
    conn.execute(sql, ("reapresentacao", "00.000.000/0001-91", "3.04.04", 1.0, 2.0, 1.0))  # outra empresa: fora
    assert dq.divergencias_camada2(conn, CNPJ) == {
        ("DRE", "ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30"): {"3.04.04": (-11.756e9, "reclassificacao")},
        ("DRE", "ITR", "2025-09-30", "Penúltimo", "2024-01-01", "2024-09-30"): {"3.04.04": (11.756e9, "reclassificacao")}}


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

def _db_com_docs():
    conn = _db()
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    docs = [d.copy() for d in ANO24]
    docs[1] = _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", R(230e6), tri=("2024-04-01", {"3.01": 125e6, "3.11": 13e6}))
    rows = [r for d in docs for r in d]
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r["periodo_ini"] if c == "dt_ini_exerc" else r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols) for r in rows])
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('l2', 2, 'cross_period')")
    conn.execute("""INSERT INTO consistency_flags (run_id, layer, check_type, classificacao, severity, cnpj_companhia, tipo_doc,
        periodo_ini, periodo_fim, fonte_ref, data_ref, ordem_ref, fonte_cmp, data_cmp, ordem_cmp)
        VALUES ('l2', 2, 'cross_period', 'reapresentacao', 'warn', ?, 'DRE', '2024-01-01', '2024-09-30',
        'ITR', '2024-09-30', 'Último', 'ITR', '2025-09-30', 'Penúltimo')""", (CNPJ,))
    conn.commit()
    return conn


def test_reapresentados_camada2_le_os_dois_lados():
    conn = _db_com_docs()
    assert dq.reapresentados_camada2(conn, CNPJ) == {("DRE", "ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30"),
                                                     ("DRE", "ITR", "2025-09-30", "Penúltimo", "2024-01-01", "2024-09-30")}


def test_main_grava_trimestrais_flags_e_substitui(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(dq, "get_db", lambda: conn)
    run1 = dq.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT trimestre, cd_conta, origem, vl_final, flag FROM demonstrativos_trimestrais WHERE run_id = ? ORDER BY trimestre, cd_conta", (run1,)).fetchall()
    assert got == [(1, "3.01", "publicado", 100e6, None), (1, "3.11", "publicado", 10e6, None),
                   (2, "3.01", "publicado", 125e6, "reapresentacao_intra_ano"), (2, "3.11", "publicado", 13e6, None),
                   (3, "3.01", "publicado", 130e6, "componente_reapresentado"), (3, "3.11", "publicado", 13e6, "componente_reapresentado"),
                   (4, "3.01", "derivado", 140e6, "componente_reapresentado"), (4, "3.11", "derivado", 14e6, "componente_reapresentado")]
    assert conn.execute("SELECT classificacao, COUNT(*) FROM consistency_flags WHERE layer = 6 GROUP BY 1 ORDER BY 1").fetchall() == \
        [("componente_reapresentado", 2), ("reapresentacao_intra_ano", 1)]
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run == (6, "derive_quarters", f"cnpj={CNPJ}", 4, 8)                     # 4 trimestres; 8 linhas
    run2 = dq.main(["--cnpj", CNPJ, "--tipo-doc", "DRE"])
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM demonstrativos_trimestrais").fetchone() == (8, 1)
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags WHERE layer = 6").fetchone() == (3, 1)
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags WHERE layer = 2").fetchone()[0] == 1
    out = capsys.readouterr().out
    assert "DRE" in out and "trimestres=4" in out and "reapresentacao_intra_ano=1" in out


def test_main_full_e_exigencia_de_cnpj(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(dq, "get_db", lambda: conn)
    run_id = dq.main(["--full"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    with pytest.raises(SystemExit):
        dq.main([])


def test_main_recusa_tabela_sem_a_flag_nova_sem_apagar_nada(monkeypatch):
    """Banco anterior à migração 2026-09-30: o CHECK antigo recusaria a flag no INSERT, depois do
    DELETE da empresa. main() tem de parar antes."""
    conn = _db_com_docs()
    monkeypatch.setattr(dq, "get_db", lambda: conn)
    dq.main(["--cnpj", CNPJ])
    antes = conn.execute("SELECT COUNT(*) FROM demonstrativos_trimestrais").fetchone()[0]
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'demonstrativos_trimestrais'").fetchone()[0]
    conn.execute("ALTER TABLE demonstrativos_trimestrais RENAME TO t_nova")
    conn.execute(ddl.replace("'reclassificacao_entre_filings',", ""))
    conn.execute("INSERT INTO demonstrativos_trimestrais SELECT * FROM t_nova")
    with pytest.raises(SystemExit, match="2026-09-30_trimestrais_reclassificacao"):
        dq.main(["--cnpj", CNPJ])
    assert conn.execute("SELECT COUNT(*) FROM demonstrativos_trimestrais").fetchone()[0] == antes > 0


def test_migracao_trimestrais_reclassificacao_recria_a_tabela_pelo_schema():
    with open(SCHEMA, encoding="utf-8") as f:
        schema = f.read()
    antigo = schema.replace("'reclassificacao_entre_filings',", "")
    assert antigo != schema
    conn = sqlite3.connect(":memory:")
    conn.executescript(antigo)
    caminho = os.path.join(os.path.dirname(__file__), "..", "scripts", "migrations", "2026-09-30_trimestrais_reclassificacao.sql")
    with open(caminho, encoding="utf-8") as f:
        conn.executescript("".join(l for l in f if not l.startswith(".")))
    conn.executescript(schema)
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'demonstrativos_trimestrais'").fetchone()[0]
    assert "'reclassificacao_entre_filings'" in ddl
