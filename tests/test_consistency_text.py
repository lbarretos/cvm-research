"""
Fase 4 da consistência financeira: Camada 5 (trilha temporal) + Camada 4 (similaridade).
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def test_schema_timeline_unique_inclui_classificacao():
    conn = _db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cd_conta_ds_timeline)")]
    assert {"run_id", "cnpj_companhia", "tipo_doc", "cd_conta_pai", "ds_conta_norm", "fonte", "data_referencia",
            "cd_conta", "ds_conta", "st_conta_fixa", "data_referencia_anterior", "cd_conta_anterior",
            "ds_conta_anterior", "similarity_score", "classificacao"} <= set(cols)
    base = ("r", CNPJ, "DFC_MI", "6.01", "x", "DFP", "2023-12-31", "6.01.05", "X", "N")
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('r', 5, 'text_stability')")
    sql = ("INSERT INTO cd_conta_ds_timeline (run_id, cnpj_companhia, tipo_doc, cd_conta_pai, ds_conta_norm, fonte, "
           "data_referencia, cd_conta, ds_conta, st_conta_fixa, classificacao) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    conn.execute(sql, base + ("removida",))
    conn.execute(sql, base + ("nova",))            # mesmo código, classe diferente: permitido (cascata)
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, base + ("nova",))        # duplicata exata: não
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, base + ("inventada",))   # CHECK


import check_text_stability as cts


def _doc(contas, data_ref, fonte="DFP", tipo_doc="DFC_MI", ordem="Último"):
    """contas = {cd: (ds, st)}; linhas no formato de latest_rows (vl_conta irrelevante aqui)."""
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": "2023-01-01", "periodo_fim": data_ref,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": 1.0, "st_conta_fixa": st}
            for cd, (ds, st) in contas.items()]


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


A = {"6.01": ("Caixa Líquido Atividades Operacionais", "S"), "6.01.01": ("Caixa Gerado nas Operações", "S"),
     "6.01.01.01": ("Lucro do Período", "N"), "6.01.01.02": ("Depreciação", "N"),
     "6.01.01.03": ("Obrigações pós emprego", "N"), "6.01.01.04": ("Partes relacionadas", "N")}


def _classes(rows):
    return {(r["cd_conta"], r["classificacao"]) for r in rows}


def test_primeiro_filing_e_primeira_ocorrencia():
    rows, flags, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31")))
    assert {r["classificacao"] for r in rows} == {"primeira_ocorrencia"} and len(rows) == 6
    r = [x for x in rows if x["cd_conta"] == "6.01.01.03"][0]
    assert (r["cnpj_companhia"], r["tipo_doc"], r["fonte"], r["data_referencia"]) == (CNPJ, "DFC_MI", "DFP", "2022-12-31")
    assert (r["cd_conta_pai"], r["ds_conta_norm"], r["st_conta_fixa"]) == ("6.01.01", "obrigacoes pos emprego", "N")
    assert r["data_referencia_anterior"] is None and r["cd_conta_anterior"] is None and r["similarity_score"] is None
    assert [x for x in rows if x["cd_conta"] == "6.01"][0]["cd_conta_pai"] == "6"
    assert flags == []
    assert stats == {"DFC_MI": {"filings": 1, "primeira_ocorrencia": 6, "estavel": 0, "renumerado": 0,
                                "reformulacao": 0, "ambiguo": 0, "nova": 0, "removida": 0}}


def test_filing_identico_so_estavel_sem_linhas():
    rows, _, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(A, "2023-12-31")))
    assert {r["classificacao"] for r in rows} == {"primeira_ocorrencia"}
    assert stats["DFC_MI"]["estavel"] == 6 and stats["DFC_MI"]["filings"] == 2


def test_renumerado_por_nome_no_mesmo_pai():
    B = dict(A); B.pop("6.01.01.02"); B["6.01.01.07"] = ("DEPRECIAÇÃO", "N")
    rows, _, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    r, = [x for x in rows if x["data_referencia"] == "2023-12-31"]
    assert (r["cd_conta"], r["classificacao"], r["cd_conta_anterior"], r["ds_conta_anterior"]) == \
        ("6.01.01.07", "renumerado", "6.01.01.02", "Depreciação")
    assert (r["ds_conta"], r["similarity_score"], r["data_referencia_anterior"]) == ("DEPRECIAÇÃO", 1.0, "2022-12-31")


def test_reformulacao_ambiguo_nova_removida_e_flag_de_ambiguo():
    B = dict(A)
    B["6.01.01.03"] = ("Obrigação de benefício pós-emprego", "N")     # score 0,75 → reformulacao (mesmo código)
    B.pop("6.01.01.04"); B["6.01.01.05"] = ("Partes relacionadas e coligadas", "N")   # score alto → reformulacao
    B["6.01.01.06"] = ("Juros pagos", "N")                             # nova
    A2 = dict(A, **{"6.01.01.08": ("Empréstimos a Clientes", "N")})
    B["6.01.01.09"] = ("Empréstimos a Clientes Líquidos de Provisão", "N")   # score ≈ 0,68 → ambiguo
    rows, flags, stats = cts.check_text_stability(_df(_doc(A2, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = {r["cd_conta"]: r for r in rows if r["data_referencia"] == "2023-12-31"}
    assert novos["6.01.01.03"]["classificacao"] == "reformulacao" and novos["6.01.01.03"]["cd_conta_anterior"] == "6.01.01.03"
    assert abs(novos["6.01.01.03"]["similarity_score"] - 0.75) < 0.01
    assert novos["6.01.01.05"]["classificacao"] == "reformulacao" and novos["6.01.01.05"]["cd_conta_anterior"] == "6.01.01.04"
    assert novos["6.01.01.06"]["classificacao"] == "nova" and novos["6.01.01.06"]["cd_conta_anterior"] is None
    assert novos["6.01.01.09"]["classificacao"] == "ambiguo" and novos["6.01.01.09"]["cd_conta_anterior"] == "6.01.01.08"
    assert 0.55 < novos["6.01.01.09"]["similarity_score"] < 0.75
    assert stats["DFC_MI"]["reformulacao"] == 2 and stats["DFC_MI"]["ambiguo"] == 1 and stats["DFC_MI"]["nova"] == 1
    f, = flags
    assert (f["layer"], f["check_type"], f["classificacao"], f["severity"], f["cd_conta"]) == \
        (5, "text_stability", "ambiguo", "warn", "6.01.01.09")
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("DFP", "2022-12-31", "DFP", "2023-12-31")
    assert f["detalhe"] == {"score": novos["6.01.01.09"]["similarity_score"], "cd_conta_anterior": "6.01.01.08",
                            "ds_conta_anterior": "Empréstimos a Clientes"}


def test_removida_com_codigo_reutilizado_gera_duas_linhas():
    # cascata: Depreciação some; Obrigações desce para o código dela
    B = dict(A); B.pop("6.01.01.03"); B["6.01.01.02"] = ("Obrigações pós emprego", "N")
    rows, _, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = _classes([r for r in rows if r["data_referencia"] == "2023-12-31"])
    assert novos == {("6.01.01.02", "renumerado"), ("6.01.01.02", "removida")}
    rem = [r for r in rows if r["classificacao"] == "removida"][0]
    assert (rem["ds_conta"], rem["cd_conta_anterior"], rem["ds_conta_anterior"], rem["data_referencia_anterior"]) == \
        ("Depreciação", "6.01.01.02", "Depreciação", "2022-12-31")


def test_linha_S_mesmo_codigo_e_estavel_mesmo_com_nome_diferente_e_nunca_ambigua():
    B = dict(A); B["6.01.01"] = ("Caixa Gerado nas Operações Continuadas", "S")
    rows, _, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    assert [r for r in rows if r["data_referencia"] == "2023-12-31"] == [] and stats["DFC_MI"]["estavel"] == 6
    B = dict(A); B.pop("6.01.01"); B["6.01.02"] = ("Caixa Gerado nas Operações Continuadas", "S")   # S sem par por nome
    rows, flags, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = _classes([r for r in rows if r["data_referencia"] == "2023-12-31"])
    assert ("6.01.02", "nova") in novos and ("6.01.01", "removida") in novos and flags == []


def test_pai_renumerado_leva_os_filhos_junto():
    B = {"6.01": A["6.01"], "6.01.02": ("Caixa Gerado nas Operações", "S"),
         "6.01.02.01": ("Lucro do Período", "N"), "6.01.02.02": ("Depreciação", "N"),
         "6.01.02.03": ("Obrigações pós emprego", "N"), "6.01.02.04": ("Partes relacionadas", "N")}
    rows, _, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = {r["cd_conta"]: r for r in rows if r["data_referencia"] == "2023-12-31"}
    assert {r["classificacao"] for r in novos.values()} == {"renumerado"} and len(novos) == 5
    assert novos["6.01.02.03"]["cd_conta_anterior"] == "6.01.01.03" and novos["6.01.02"]["cd_conta_anterior"] == "6.01.01"
    assert stats["DFC_MI"]["nova"] == 0 and stats["DFC_MI"]["removida"] == 0


def test_pai_removido_leva_os_filhos_e_pai_novo_traz_filhos_novos():
    B = {"6.01": A["6.01"], "6.03": ("Caixa Líquido Atividades de Financiamento", "S"), "6.03.01": ("Dividendos", "N")}
    rows, _, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = _classes([r for r in rows if r["data_referencia"] == "2023-12-31"])
    assert ("6.01.01", "removida") in novos and ("6.01.01.01", "removida") in novos
    assert ("6.03", "nova") in novos and ("6.03.01", "nova") in novos


def test_sequencias_separadas_por_fonte_e_tipo_e_penultimo_ignorado():
    df = _df(_doc(A, "2022-12-31"), _doc(A, "2023-03-31", fonte="ITR"), _doc(A, "2022-12-31", ordem="Penúltimo"),
             _doc({"3.01": ("Receita", "S")}, "2022-12-31", tipo_doc="DRE"))
    rows, _, stats = cts.check_text_stability(df)
    assert {r["classificacao"] for r in rows} == {"primeira_ocorrencia"} and len(rows) == 13
    assert stats["DFC_MI"]["filings"] == 2 and stats["DRE"]["filings"] == 1
    assert cts.check_text_stability(pd.DataFrame()) == ([], [], {})


def test_limiares_parametrizados():
    A2 = dict(A, **{"6.01.01.08": ("Empréstimos a Clientes", "N")})
    B = dict(A, **{"6.01.01.09": ("Empréstimos a Clientes Líquidos de Provisão", "N")})   # score ≈ 0,68
    rows, _, _ = cts.check_text_stability(_df(_doc(A2, "2022-12-31"), _doc(B, "2023-12-31")), sim_alto=0.5)
    assert [r["classificacao"] for r in rows if r["data_referencia"] == "2023-12-31"] == ["reformulacao"]
    rows, _, _ = cts.check_text_stability(_df(_doc(A2, "2022-12-31"), _doc(B, "2023-12-31")), sim_baixo=0.7)
    assert _classes([r for r in rows if r["data_referencia"] == "2023-12-31"]) == {("6.01.01.09", "nova"), ("6.01.01.08", "removida")}


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

def _db_com_docs():
    conn = _db()
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    A2 = dict(A, **{"6.01.01.08": ("Empréstimos a Clientes", "N")})
    B = dict(A); B.pop("6.01.01.02"); B["6.01.01.07"] = ("Depreciação", "N"); B["6.01.01.09"] = ("Empréstimos a Clientes Líquidos de Provisão", "N")
    rows = _doc(A2, "2022-12-31") + _doc(B, "2023-12-31")
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r["periodo_ini"] if c == "dt_ini_exerc" else r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols)
         for r in rows],
    )
    conn.commit()
    return conn


def test_main_grava_timeline_flags_e_substitui(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(cts, "get_db", lambda: conn)
    run1 = cts.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT classificacao, COUNT(*) FROM cd_conta_ds_timeline WHERE run_id = ? GROUP BY 1 ORDER BY 1",
                       (run1,)).fetchall()
    assert got == [("ambiguo", 1), ("primeira_ocorrencia", 7), ("renumerado", 1)]
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags WHERE run_id = ? AND layer = 5 AND classificacao = 'ambiguo'",
                        (run1,)).fetchone()[0] == 1
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, script_args FROM consistency_runs "
                       "WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (5, "text_stability", f"cnpj={CNPJ}", 2, 9)      # 2 filings; 9 linhas na timeline
    assert '"sim_alto": 0.75' in run[5]
    run2 = cts.main(["--cnpj", CNPJ, "--tipo-doc", "DFC_MI"])
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM cd_conta_ds_timeline").fetchone() == (9, 1)
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags").fetchone() == (1, 1)
    assert conn.execute("SELECT DISTINCT run_id FROM cd_conta_ds_timeline").fetchone()[0] == run2
    out = capsys.readouterr().out
    assert "DFC_MI" in out and "filings=2" in out and "renumerado=1" in out and "ambiguo=1" in out


def test_main_full_e_exigencia_de_cnpj(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(cts, "get_db", lambda: conn)
    run_id = cts.main(["--full", "--sim-alto", "0.5"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    assert conn.execute("SELECT COUNT(*) FROM cd_conta_ds_timeline WHERE classificacao = 'reformulacao'").fetchone()[0] == 1
    import pytest
    with pytest.raises(SystemExit):
        cts.main([])


# ── match_filings: casamento reaproveitado pela Camada 6 ─────────────────────

def test_match_filings_devolve_par_classe_e_score():
    anterior = {"6.03": ("Financiamento", "S"),
                "6.03.01": ("Pagamento de empréstimos", "N"),
                "6.03.06": ("Pagamento de encargos e debêntures", "N"),
                "6.03.08": ("Dividendos e juros sobre capital próprio", "N")}
    atual = {"6.03": ("Financiamento", "S"),
             "6.03.01": ("Pagamento de empréstimos", "N"),
             "6.03.08": ("Pagamento de encargos sobre debêntures", "N"),
             "6.03.09": ("Dividendos e juros sobre capital próprio", "N"),
             "6.03.11": ("Exercício de ações restritas", "N")}
    par = cts.match_filings(anterior, atual)
    assert par["6.03"] == ("6.03", "estavel", None)
    assert par["6.03.01"] == ("6.03.01", "estavel", None)
    assert par["6.03.09"] == ("6.03.08", "renumerado", 1.0)          # nome idêntico, código novo
    cd_b, classe, score = par["6.03.08"]
    assert (cd_b, classe) == ("6.03.06", "reformulacao") and score >= 0.75
    assert "6.03.11" not in par                                      # linha nova: sem par


def test_match_filings_marca_ambiguo_sem_casar_silenciosamente():
    anterior = {"6.03": ("Financiamento", "S"), "6.03.09": ("Captação de debêntures", "N")}
    atual = {"6.03": ("Financiamento", "S"), "6.03.12": ("Emissão de debêntures", "N")}
    cd_b, classe, score = cts.match_filings(anterior, atual)["6.03.12"]
    assert (cd_b, classe) == ("6.03.09", "ambiguo") and 0.55 < score < 0.75


def test_match_filings_vazio_dos_dois_lados():
    assert cts.match_filings({}, {}) == {}
    assert cts.match_filings({}, {"3.01": ("Receita", "S")}) == {}


def test_compare_filings_devolve_o_mapa_anterior_para_atual():
    anterior = {"6.01": ("Operacional", "S"), "6.01.01": ("Depreciação", "N")}
    atual = {"6.01": ("Operacional", "S"), "6.01.07": ("Depreciação", "N")}
    rows, estaveis, mapa = cts.compare_filings(anterior, atual)
    assert mapa == {"6.01": "6.01", "6.01.01": "6.01.07"} and estaveis == 1
    assert [r["classificacao"] for r in rows] == ["renumerado"]


def test_match_filings_nao_confia_cegamente_no_codigo_fixo_da_cvm():
    """Itaú, DRE 2017: a CVM re-letrou o plano dos bancos e 3.01.02 deixou de ser
    'Receita de Dividendos' para virar o resultado de câmbio. Casar contas 'S' pelo
    código, como a Camada 5 faz, subtrairia uma linha da outra na Camada 6."""
    anterior = {"3.01": ("Receitas", "S"), "3.01.02": ("Receita de Dividendos", "S"),
                "3.01.03": ("Resultado de Operações de Câmbio", "S")}
    atual = {"3.01": ("Receitas", "S"), "3.01.02": ("Resultado de Operações de Câmbio", "S"),
             "3.01.03": ("Ganho (Perda) Líquido com Ativos Financeiros", "S")}
    par = cts.match_filings(anterior, atual)
    assert par["3.01"] == ("3.01", "estavel", None)
    assert par["3.01.02"] == ("3.01.03", "renumerado", 1.0)      # o câmbio veio do 3.01.03
    assert "3.01.03" not in par                                   # 'Ganho (Perda)' é linha nova

    # A Camada 5 mantém a regra documentada: código fixo igual é estável mesmo com outro nome.
    _rows, estaveis, mapa = cts.compare_filings(anterior, atual)
    assert mapa["3.01.02"] == "3.01.02" and estaveis == 3
    # E match_filings devolve a mesma coisa quando se pede a regra da Camada 5.
    assert cts.match_filings(anterior, atual, codigo_fixo_confiavel=True)["3.01.02"] == ("3.01.02", "estavel", None)


def test_polaridade_invertida_nao_vira_reformulacao():
    """Multiplan, DFC 2021: o ITR do 3T não tinha 'Pagamento de debêntures', e a
    similaridade de 0,756 casava a linha do DFP com 'Captação de debêntures'.
    Sentido oposto não casa em silêncio: cai na fila de revisão."""
    anterior = {"6.03": ("Financiamento", "S"), "6.03.09": ("Captação de debêntures", "N")}
    atual = {"6.03": ("Financiamento", "S"), "6.03.14": ("Pagamento de debêntures", "N")}
    cd_b, classe, score = cts.match_filings(anterior, atual)["6.03.14"]
    assert (cd_b, classe) == ("6.03.09", "ambiguo") and score >= 0.75

    # Sem conflito de sentido, o mesmo score continua sendo reformulacao.
    ok = cts.match_filings({"6.03": ("Financiamento", "S"), "6.03.06": ("Pagamento de encargos e debêntures", "N")},
                           {"6.03": ("Financiamento", "S"), "6.03.08": ("Pagamento de encargos sobre debêntures", "N")})
    assert ok["6.03.08"][1] == "reformulacao"
