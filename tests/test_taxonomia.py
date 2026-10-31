"""Etapa 7: regras, voto por linha econômica e fatos de scripts/analysis/taxonomia.py."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

import taxonomia as t  # noqa: E402
from consistency_utils import normalize_text  # noqa: E402


def cls(cd, nome, vl=None):
    return t.classificar(cd, normalize_text(nome), vl)


def test_juros_so_no_fluxo_de_caixa_e_nao_provisao():
    # o ajuste de 6.01.01 (provisão somada de volta) não é caixa pago
    assert cls("6.01.01.04", "Juros provisionados sobre empréstimos") is None
    assert cls("6.01.01.04", "Juros sobre empréstimos") is None
    assert cls("6.01.02.03", "Juros pagos") == "juros_pagos"
    assert cls("6.03.04", "Pagamento de juros sobre empréstimos e financiamentos") == "juros_pagos"
    assert cls("6.01.02.13", "Salários e encargos a pagar") is None


def test_regra_especifica_vence_a_geral_sem_conflito():
    assert cls("6.02.01", "Aquisição de imobilizado e intangível") == "capex_conjunto"
    assert cls("6.02.01", "Aquisição de imobilizado") == "capex_imob"
    assert cls("6.03.01", "Captação e amortização de empréstimos, líquido") == "divida_liquida_fluxo"
    assert cls("6.03.02", "Captação de empréstimos e financiamentos") == "capt_divida"


def test_exclusoes_do_stress_test():
    assert cls("6.03.05", "Caixa recebido na operação de sale and leaseback") is None
    assert cls("6.01.02.11", "Impostos a recolher e provisão IR e CS") is None
    assert cls("6.03.06", "Pagamento de arrendamento mercantil") == "arrend_pago"
    assert cls("6.03.02", "Recompra de debêntures") is None
    assert cls("6.01.01.05", "Amortização de mais valia de ativos") == "da_ppa"
    assert cls("6.01.01.02", "Depreciação e amortização") == "da_ex_ppa"
    assert cls("6.01.01.06", "Amortização de direito de uso") == "da_direito_uso"


def test_sinal_contrario_nao_vira_conceito():
    assert cls("6.03.06", "Ações em tesouraria", -100.0) == "recompra"
    assert cls("6.03.06", "Ações em tesouraria", +100.0) is None     # venda/exercício de opção


def test_voto_so_propaga_se_a_maioria_da_linha_foi_classificada():
    linhas = pd.DataFrame({
        "linha_id": ["a"] * 4 + ["b"] * 4,
        "conceito": ["recompra", "recompra", None, None] + ["recompra", None, None, None],
    })
    v = t.votar(linhas)
    assert v["a"][0] == "recompra" and v["a"][3] is True      # metade classificada: propaga
    assert v["b"][0] == "recompra" and v["b"][3] is False     # 1 de 4: fica só onde a regra pegou


def _filing(fonte, data, linhas, ini="2024-01-01", fim=None):
    fim = fim or data
    rows = []
    for cd, ds, vl, st in linhas:
        rows.append({"cnpj_companhia": "C", "tipo_doc": "DFC_MI", "fonte": fonte, "data_referencia": data,
                     "ordem_exercicio": "Último", "periodo_ini": ini, "periodo_fim": fim, "cd_conta": cd,
                     "ds_conta": ds, "vl_conta": vl, "st_conta_fixa": st, "plano_contas": "padrao"})
    return rows


def test_fatos_somam_derivam_e_checam_com_a_dva():
    rows = _filing("DFP", "2024-12-31", [
        ("6.01", "Caixa das Atividades Operacionais", 500.0, "S"),
        ("6.01.01", "Caixa Gerado nas Operações", 300.0, "S"),
        ("6.01.01.02", "Depreciação e amortização", 100.0, "N"),
        ("6.01.01.03", "Amortização de direito de uso", 20.0, "N"),
        ("6.02", "Caixa das Atividades de Investimento", -80.0, "S"),
        ("6.02.01", "Aquisição de imobilizado", -50.0, "N"),
        ("6.02.02", "Aquisição de intangível", -30.0, "N"),
    ])
    rows.append({"cnpj_companhia": "C", "tipo_doc": "DVA", "fonte": "DFP", "data_referencia": "2024-12-31",
                 "ordem_exercicio": "Último", "periodo_ini": "2024-01-01", "periodo_fim": "2024-12-31",
                 "cd_conta": "7.04.01", "ds_conta": "Depreciação, amortização e exaustão", "vl_conta": 120.0,
                 "st_conta_fixa": "S", "plano_contas": "padrao"})
    lc, fatos = t.fatos_da_empresa(pd.DataFrame(rows), {}, "C")
    f = {x[5]: x for x in fatos}
    assert f["da_total"][6] == 120.0 and f["da_total"][10] == "ok" and f["da_total"][11] == 1
    assert f["capex_total"][6] == -80.0 and f["capex_total"][10] == "ok"
    assert f["cfo"][8] == "S" and f["cfo"][6] == 500.0
    # a DVA diverge e nenhuma definição alternativa fecha: não publica
    rows[-1]["vl_conta"] = 999.0
    _, fatos2 = t.fatos_da_empresa(pd.DataFrame(rows), {}, "C")
    d = {x[5]: x for x in fatos2}["da_total"]
    assert d[10] == "divergente" and d[11] == 0


def test_dva_com_definicao_alternativa_fecha():
    rows = _filing("DFP", "2024-12-31", [
        ("6.01.01.02", "Depreciação e amortização", 100.0, "N"),
        ("6.01.01.03", "Amortização de direito de uso", 20.0, "N"),
    ])
    rows.append({"cnpj_companhia": "C", "tipo_doc": "DVA", "fonte": "DFP", "data_referencia": "2024-12-31",
                 "ordem_exercicio": "Último", "periodo_ini": "2024-01-01", "periodo_fim": "2024-12-31",
                 "cd_conta": "7.04.01", "ds_conta": "Depreciação", "vl_conta": 100.0, "st_conta_fixa": "S",
                 "plano_contas": "padrao"})
    _, fatos = t.fatos_da_empresa(pd.DataFrame(rows), {}, "C")
    d = {x[5]: x for x in fatos}["da_total"]
    assert d[10] == "ok_sem_uso" and d[11] == 1   # a + mais-valia (0) = DVA


def test_get_financials_filtra_publicados_e_pede_checagem(tmp_path, monkeypatch):
    import sqlite3 as sq
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "mcp"))
    import cvm_mcp
    path = tmp_path / "f.db"
    c = sq.connect(path)
    c.executescript("CREATE TABLE companies (cnpj TEXT, ticker TEXT, nome_cvm TEXT, setor TEXT);"
                    "INSERT INTO companies VALUES ('1','WEGE3','WEG','Industria');")
    c.executescript(t.DDL)
    c.executemany("INSERT INTO fato_padronizado VALUES ('1','DFP',?, '2024-01-01','2024-12-31',?,?,?,?,?,?,?)", [
        ("2024-12-31", "da_total", 120.0, 2, "derivado", 1.0, "ok", 1),
        ("2024-12-31", "capex_total", -80.0, 2, "derivado", 1.0, "divergente", 0)])
    c.commit()
    c.close()
    monkeypatch.setattr(cvm_mcp, "DB_PATH", path)
    r = cvm_mcp.get_financials("WEGE3")
    assert [x[3] for x in r["linhas"]] == ["da_total"]
    assert r["colunas"][-2:] == ["checagem", "publicado"]
    todos = cvm_mcp.get_financials("WEGE3", incluir_nao_publicados=True)
    assert {x[3] for x in todos["linhas"]} == {"da_total", "capex_total"}
    assert cvm_mcp.get_financials("XXXX3")["linhas"] == []


def test_fatos_dmpl_contas_fixas_e_dividendos_em_conta_propria():
    import sqlite3
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))
    import dmpl
    conn = sqlite3.connect(":memory:")
    assert t.fatos_dmpl(conn, "C") == []                     # banco sem a tabela
    dmpl.garantir_schema(conn)
    base = ("C", "DFP", "2011-12-31", 1, "Último", "2011-01-01", "2011-12-31")
    linhas = [("5.04.01", "pl_consolidado", "Aumentos de Capital", 0.0, "S"),
              ("5.04.04", "pl_consolidado", "Ações em Tesouraria Adquiridas", -40e6, "S"),
              ("5.04.06", "pl_consolidado", "Dividendos", -751e6, "S"),
              ("5.04.06", "pl", "Dividendos", -747e6, "S"),                                   # outra coluna: fora
              ("5.04.09", "pl_consolidado", "Aprovação da Proposta de Dividendo", -490e6, "N"),
              ("5.04.10", "pl_consolidado", "Dividendo Prescrito", 5e6, "N"),                 # positivo/prescrito: fora
              ("5.04.08", "pl_consolidado", "Combinação de negócios", 1414e6, "N")]           # sem dividendo: fora
    conn.executemany("INSERT INTO dmpl VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     [base + (cd, col, ds, vl, st) for cd, col, ds, vl, st in linhas])
    # versão antiga do mesmo filing não entra
    conn.execute("INSERT INTO dmpl VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("C", "DFP", "2011-12-31", 0, "Último", "2011-01-01", "2011-12-31", "5.04.06", "pl_consolidado", "Dividendos", -1.0, "S"))
    f = {x[5]: x for x in t.fatos_dmpl(conn, "C")}
    assert f["dividendos_declarados"][6] == -1241e6 and f["dividendos_declarados"][8] == "S"
    assert f["recompra_dmpl"][6] == -40e6 and f["aumento_capital"][6] == 0.0
