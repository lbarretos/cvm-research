"""
fre_posicao_acionaria: separar os acionistas diretos da cadeia de controle.

Cobre:
  - process_posicao_acionaria grava ID_Acionista_Relacionado (vazio → NULL)
  - CSV sem a coluna falha em vez de marcar a cadeia inteira como direta
  - vw_acionistas_diretos: só linhas diretas, só o FRE mais recente (data, depois versão)
  - migração 2026-09-29 num banco com o layout antigo
"""
import io
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _upsert_sqlite
import ingest_fre

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCHEMA = os.path.join(ROOT, "schema.sql")
MIGRATION = os.path.join(ROOT, "scripts", "migrations", "2026-09-29_fre_acionista_relacionado.sql")

WEG = "84.429.695/0001-11"
CONFLICT = "cnpj_companhia,data_referencia,versao,id_acionista"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _csv_row(id_acionista, acionista, pct, relacionado="", data="2026-12-31", versao="2", cnpj=WEG, cpf_cnpj=""):
    return {
        "CNPJ_Companhia": cnpj, "Nome_Companhia": "WEG S.A.",
        "Data_Referencia": data, "Versao": versao, "ID_Documento": "1",
        "ID_Acionista": str(id_acionista), "ID_Acionista_Relacionado": relacionado,
        "Acionista": acionista, "Tipo_Pessoa_Acionista": "PJ", "CPF_CNPJ_Acionista": cpf_cnpj,
        "Percentual_Total_Acoes_Circulacao": pct, "Acionista_Controlador": "S",
    }


# Recorte do FRE 2026 da WEG (fre_cia_aberta_posicao_acionaria_2026.csv, IDs reais):
# WPA → G Werninghaus → Diether Werninghaus → ANNE MARIE (33,333% da holding de 3º nível).
# ANNE MARIE também é acionista direta (0,000%): a mesma pessoa aparece nos dois níveis,
# com ID_Acionista diferente em cada linha.
WEG_CSV = [
    _csv_row(8228789, "WPA Participações e Serviços S.A.", "50.088000", cpf_cnpj="00.000.000/0001-00"),
    _csv_row(8228895, "Outros", "34.796000"),
    _csv_row(8228547, "ANNE MARIE WERNINGHAUS", "0.000000"),
    _csv_row(8228848, "G Werninghaus Administradora Ltda", "33.333000", relacionado="8228789"),
    _csv_row(8228849, "Diether Werninghaus Administradora Ltda", "25.000000", relacionado="8228848"),
    _csv_row(8228850, "ANNE MARIE WERNINGHAUS", "33.333000", relacionado="8228849"),
]


def _carrega(conn, linhas):
    rows = ingest_fre.process_posicao_acionaria(pd.DataFrame(linhas, dtype=str), {WEG, "11.111.111/0001-11"})
    _upsert_sqlite(conn, "fre_posicao_acionaria", rows, CONFLICT)


def test_process_grava_relacionado():
    rows = ingest_fre.process_posicao_acionaria(pd.DataFrame(WEG_CSV, dtype=str), {WEG})
    got = {r["id_acionista"]: r["id_acionista_relacionado"] for r in rows}
    assert got == {
        8228789: None, 8228895: None, 8228547: None,
        8228848: 8228789, 8228849: 8228848, 8228850: 8228849,
    }
    assert rows[0]["cpf_cnpj_acionista"] == "00.000.000/0001-00"


def test_process_relacionado_nan_vira_null():
    """pandas lê célula vazia como NaN mesmo com dtype=str."""
    df = pd.read_csv(
        io.StringIO(
            "CNPJ_Companhia;Data_Referencia;Versao;ID_Acionista;ID_Acionista_Relacionado;Acionista\n"
            f"{WEG};2026-12-31;2;10;;WPA\n"
            f"{WEG};2026-12-31;2;20;10;ANNE\n"
        ),
        sep=";", dtype=str,
    )
    rows = ingest_fre.process_posicao_acionaria(df, {WEG})
    assert [r["id_acionista_relacionado"] for r in rows] == [None, 10]


def test_process_sem_coluna_falha():
    df = pd.DataFrame(WEG_CSV, dtype=str).drop(columns=["ID_Acionista_Relacionado"])
    with pytest.raises(ValueError, match="ID_Acionista_Relacionado"):
        ingest_fre.process_posicao_acionaria(df, {WEG})


def test_view_so_diretos():
    conn = _db()
    _carrega(conn, WEG_CSV)
    got = conn.execute(
        "SELECT acionista, percentual_total_acoes_circulacao FROM vw_acionistas_diretos "
        "WHERE cnpj_companhia = ? ORDER BY percentual_total_acoes_circulacao DESC", (WEG,)
    ).fetchall()
    assert got == [
        ("WPA Participações e Serviços S.A.", 50.088),
        ("Outros", 34.796),
        ("ANNE MARIE WERNINGHAUS", 0.0),
    ]


def test_cadeia_sobe_por_id_acionista():
    """ID_Acionista_Relacionado aponta para o ID_Acionista da holding de cima, no mesmo documento."""
    conn = _db()
    _carrega(conn, WEG_CSV)
    got = conn.execute(
        "WITH RECURSIVE cadeia(id, nivel) AS ("
        "  SELECT id_acionista, 0 FROM fre_posicao_acionaria WHERE id_acionista = 8228850"
        "  UNION ALL"
        "  SELECT p.id_acionista_relacionado, c.nivel + 1 FROM cadeia c"
        "  JOIN fre_posicao_acionaria p ON p.id_acionista = c.id"
        "  WHERE p.id_acionista_relacionado IS NOT NULL)"
        "SELECT p.acionista FROM cadeia c JOIN fre_posicao_acionaria p ON p.id_acionista = c.id ORDER BY c.nivel"
    ).fetchall()
    assert [r[0] for r in got] == [
        "ANNE MARIE WERNINGHAUS", "Diether Werninghaus Administradora Ltda",
        "G Werninghaus Administradora Ltda", "WPA Participações e Serviços S.A.",
    ]


def test_view_so_fre_mais_recente():
    conn = _db()
    _carrega(conn, [
        # versão anterior do mesmo FRE e FRE do ano anterior: não entram
        _csv_row(1, "Acionista versao 1", "60", versao="1"),
        _csv_row(2, "Acionista 2025", "70", data="2025-12-31", versao="5"),
        *WEG_CSV,
        # outra empresa, FRE mais antigo: tem o seu próprio "mais recente"
        _csv_row(3, "Controlador Outra", "55", data="2024-12-31", versao="1", cnpj="11.111.111/0001-11"),
    ])
    got = conn.execute(
        "SELECT cnpj_companhia, data_referencia, versao, acionista FROM vw_acionistas_diretos "
        "ORDER BY cnpj_companhia, acionista"
    ).fetchall()
    assert got == [
        ("11.111.111/0001-11", "2024-12-31", 1, "Controlador Outra"),
        (WEG, "2026-12-31", 2, "ANNE MARIE WERNINGHAUS"),
        (WEG, "2026-12-31", 2, "Outros"),
        (WEG, "2026-12-31", 2, "WPA Participações e Serviços S.A."),
    ]


def test_upsert_atualiza_relacionado():
    """Reingestão do mesmo FRE preenche a coluna nas linhas já existentes."""
    conn = _db()
    rows = ingest_fre.process_posicao_acionaria(pd.DataFrame(WEG_CSV, dtype=str), {WEG})
    for r in rows:
        r_sem = dict(r, id_acionista_relacionado=None)
        _upsert_sqlite(conn, "fre_posicao_acionaria", [r_sem], CONFLICT)
    _upsert_sqlite(conn, "fre_posicao_acionaria", rows, CONFLICT)
    got = conn.execute(
        "SELECT COUNT(*), COUNT(id_acionista_relacionado) FROM fre_posicao_acionaria"
    ).fetchone()
    assert got == (6, 3)


def test_migracao_banco_antigo():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE fre_posicao_acionaria ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, cnpj_companhia TEXT NOT NULL,"
        " nome_companhia TEXT, data_referencia TEXT, versao INTEGER, id_documento INTEGER,"
        " id_acionista INTEGER, acionista TEXT, tipo_pessoa_acionista TEXT, cpf_cnpj_acionista TEXT,"
        " quantidade_acao_ordinaria_circulacao INTEGER, percentual_acao_ordinaria_circulacao REAL,"
        " quantidade_acao_preferencial_circulacao INTEGER, percentual_acao_preferencial_circulacao REAL,"
        " quantidade_total_acoes_circulacao INTEGER, percentual_total_acoes_circulacao REAL,"
        " nacionalidade TEXT, residente_exterior TEXT, acionista_controlador TEXT,"
        " participante_acordo_acionistas TEXT, data_composicao_capital_social TEXT,"
        " created_at TEXT DEFAULT (datetime('now')),"
        " UNIQUE (cnpj_companhia, data_referencia, versao, id_acionista));"
        f"INSERT INTO fre_posicao_acionaria (cnpj_companhia, acionista) VALUES ('{WEG}', 'ANNE');"
    )
    with open(MIGRATION, encoding="utf-8") as f:
        # .bail é diretiva do cliente sqlite3, não SQL
        sql = "\n".join(l for l in f.read().splitlines() if not l.startswith("."))
    conn.executescript(sql)
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())

    cols = {r[1] for r in conn.execute("PRAGMA table_info(fre_posicao_acionaria)")}
    assert "id_acionista_relacionado" in cols
    assert conn.execute("SELECT COUNT(*) FROM fre_posicao_acionaria").fetchone() == (0,)
    _carrega(conn, WEG_CSV)
    assert conn.execute("SELECT COUNT(*) FROM vw_acionistas_diretos").fetchone() == (3,)
