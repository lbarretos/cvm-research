"""
Etapa 6: linha econômica por empresa (scripts/analysis/linha_economica.py). O encadeamento é o mesmo do
visualizador (tests/test_viewer.py cobre o comportamento base); aqui o que a tabela acrescenta:
linha_id estável, fila `ambiguo`, decisões humanas e o reatamento pelo (pai, nome).
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

import linha_economica as le  # noqa: E402

CNPJ = "11.111.111/0001-11"


def col(**contas):
    return {cd: (ds, "N") for cd, ds in contas.items()}


def df_de(filings):
    """filings = [(data, fonte, {cd: nome})] → saída no formato de latest_rows (só o que o builder lê)."""
    rows = []
    for data, fonte, contas in filings:
        for cd, ds in contas.items():
            rows.append({"cnpj_companhia": CNPJ, "tipo_doc": "DFC_MI", "fonte": fonte, "data_referencia": data,
                         "ordem_exercicio": "Último", "cd_conta": cd, "ds_conta": ds, "st_conta_fixa": "N"})
    return pd.DataFrame(rows)


def por_data(rows):
    return {(r[3], r[4]): r for r in rows}   # (data, cd_conta) → tupla de linha_empresa


# índices da tupla: cnpj, tipo_doc, fonte, data, cd, linha_id, ds, st, casamento, score, anterior
LID, CAS, ANT = 5, 8, 10

A = {"6.03.01": "Captação de debêntures", "6.03.02": "Dividendos pagos"}
B = {"6.03.01": "Pagamento de debêntures", "6.03.02": "Dividendos pagos"}   # sentido oposto: sempre ambíguo


def test_par_ambiguo_nao_encadeia_e_vai_para_a_fila():
    rows = le.linhas_da_empresa(df_de([("2024-09-30", "ITR", A), ("2024-12-31", "DFP", B)]), CNPJ)
    r = por_data(rows)
    assert r[("2024-12-31", "6.03.02")][LID] == r[("2024-09-30", "6.03.02")][LID]          # estável encadeia
    amb = r[("2024-12-31", "6.03.01")]
    assert amb[CAS] == "ambiguo" and amb[ANT] == "6.03.01"
    assert amb[LID] != r[("2024-09-30", "6.03.01")][LID]                                    # linha nova


def test_decisao_mesma_liga_e_diferente_bloqueia():
    filings = [("2024-09-30", "ITR", A), ("2024-12-31", "DFP", B)]
    mesma = {"DFC_MI": [("6.03.01", "2024-09-30", "6.03.01", "2024-12-31", "mesma")]}
    r = por_data(le.linhas_da_empresa(df_de(filings), CNPJ, mesma))
    assert r[("2024-12-31", "6.03.01")][LID] == r[("2024-09-30", "6.03.01")][LID]
    assert r[("2024-12-31", "6.03.01")][CAS] == "decisao"

    # 'diferente' impede um casamento que o automático faria (renumeração por nome)
    novo = {"6.03.05": "Dividendos pagos", "6.03.01": "Captação de debêntures"}
    base = [("2024-09-30", "ITR", {"6.03.02": "Dividendos pagos", "6.03.01": "Captação de debêntures"}),
            ("2024-12-31", "DFP", novo)]
    auto = por_data(le.linhas_da_empresa(df_de(base), CNPJ))
    assert auto[("2024-12-31", "6.03.05")][LID] == auto[("2024-09-30", "6.03.02")][LID]
    bloq = {"DFC_MI": [("6.03.02", "2024-09-30", "6.03.05", "2024-12-31", "diferente")]}
    r2 = por_data(le.linhas_da_empresa(df_de(base), CNPJ, bloq))
    assert r2[("2024-12-31", "6.03.05")][LID] != r2[("2024-09-30", "6.03.02")][LID]


def test_linha_id_e_estavel_quando_chega_um_filing_novo():
    f1 = ("2024-09-30", "ITR", A)
    f2 = ("2024-12-31", "DFP", {"6.03.01": "Captação de debêntures", "6.03.02": "Dividendos pagos"})
    f3 = ("2025-03-31", "ITR", {"6.03.01": "Captação de debêntures", "6.03.02": "Dividendos pagos"})
    antes = por_data(le.linhas_da_empresa(df_de([f1, f2]), CNPJ))
    depois = por_data(le.linhas_da_empresa(df_de([f1, f2, f3]), CNPJ))
    for k, row in antes.items():
        assert depois[k][LID] == row[LID]
    assert depois[("2025-03-31", "6.03.02")][LID] == antes[("2024-12-31", "6.03.02")][LID]


def test_reata_pelo_pai_e_nome_depois_de_buraco():
    cols = [
        col(**{"6.03.02": "Pagamento de dividendos", "6.03.09": "Outra"}),
        col(**{"6.03.09": "Outra"}),                       # a linha some por um filing
        col(**{"6.03.05": "Pagamento de dividendos", "6.03.09": "Outra"}),   # volta com outro código
    ]
    sem = le.encadear(cols)
    com = le.encadear(cols, reatar_por_pai=True)
    assert len(com) == len(sem) - 1
    achada = [s for s in com if s.get(0) == "6.03.02"][0]
    assert achada == {0: "6.03.02", 2: "6.03.05"}


def test_construir_grava_a_tabela_e_a_fila(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "l.db")
    conn.executescript(le.DDL)
    rows = le.linhas_da_empresa(df_de([("2024-09-30", "ITR", A), ("2024-12-31", "DFP", B)]), CNPJ)
    conn.executemany("INSERT INTO linha_empresa VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    fila = le.listar_ambiguos(conn, CNPJ)
    assert [(r[0], r[2], r[3], r[5]) for r in fila] == [("DFC_MI", "2024-12-31", "6.03.01", "6.03.01")]
