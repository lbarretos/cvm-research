"""
VLMO: a recarga do mesmo CSV não pode duplicar linhas.

'Saldo Inicial' tem Data_Movimentacao vazia; com uma UNIQUE comum o NULL nunca
conflitava e cada carga inseria os saldos de novo (Petrobras 07/2026: o saldo ON
do controlador aparecia 3 vezes). vlmo_mov_uniq agora é índice de expressão.
"""
import io
import os
import sqlite3
import sys
import zipfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import upsert
import ingest_vlmo

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCHEMA = os.path.join(ROOT, "schema.sql")
MIGRATION = os.path.join(ROOT, "scripts", "migrations", "2026-09-30_vlmo_mov_uniq_nulls.sql")
PETR = "33.000.167/0001-01"

HEADER = ("CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Tipo_Empresa;Empresa;"
          "Tipo_Cargo;Tipo_Movimentacao;Descricao_Movimentacao;Tipo_Operacao;Tipo_Ativo;"
          "Caracteristica_Valor_Mobiliario;Intermediario;Data_Movimentacao;Quantidade;"
          "Preco_Unitario;Volume")
LINHAS = [
    # Saldos: Data_Movimentacao vazia
    f"{PETR};PETROBRAS;2026-07-01;1;Companhia;PETROBRAS;Controlador ou Vinculado;Saldo Inicial;;Crédito;Ações;ON;;;7442231382;;",
    f"{PETR};PETROBRAS;2026-07-01;1;Companhia;PETROBRAS;Diretor ou Vinculado;Saldo Inicial;;Crédito;Ações;PN;;;15300;;",
    # Tipo_Cargo e característica vazios também acontecem
    f"{PETR};PETROBRAS;2026-07-01;1;Companhia;PETROBRAS;;Saldo Inicial;;Crédito;Ações;;;;100;;",
    # Movimentação com data
    f"{PETR};PETROBRAS;2026-07-01;1;Companhia;PETROBRAS;Diretor ou Vinculado;Compra à vista;;Crédito;Ações;PN;XP;2026-07-15;1000;35,10;35100",
]


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _zip_response():
    csv = (HEADER + "\n" + "\n".join(LINHAS) + "\n").encode("latin-1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("vlmo_cia_aberta_con_2026.csv", csv)
    return MagicMock(content=buf.getvalue())


def _carga(conn):
    with patch("ingest_vlmo._http_get", return_value=_zip_response()):
        _, movs = ingest_vlmo.download_year(2026)
    upsert(conn, "vlmo_movimentacoes", ingest_vlmo.process_movimentacoes(movs, {PETR}),
           conflict="vlmo_mov_uniq")


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM vlmo_movimentacoes").fetchone()[0]


def _run_sql(conn, path):
    with open(path, encoding="utf-8") as f:
        sql = "".join(l for l in f if not l.startswith("."))  # .bail é do cliente sqlite3
    conn.executescript(sql)


def test_mesmo_csv_duas_vezes_nao_cresce():
    conn = _db()
    _carga(conn)
    assert _count(conn) == len(LINHAS)
    _carga(conn)
    _carga(conn)
    assert _count(conn) == len(LINHAS)
    saldos = conn.execute(
        "SELECT COUNT(*) FROM vlmo_movimentacoes WHERE data_movimentacao IS NULL").fetchone()[0]
    assert saldos == 3


def test_recarga_atualiza_linha_de_saldo():
    """O conflito em NULL agora dispara o DO UPDATE: a última carga vence."""
    conn = _db()
    _carga(conn)
    conn.execute("UPDATE vlmo_movimentacoes SET nome_companhia = 'antigo'")
    _carga(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM vlmo_movimentacoes WHERE nome_companhia = 'antigo'").fetchone()[0] == 0


def test_migracao_remove_duplicatas_e_recria_indice():
    conn = _db()
    # Banco anterior à correção: índice por colunas, onde NULL não conflita
    conn.executescript("""
        DROP INDEX vlmo_mov_uniq;
        CREATE UNIQUE INDEX vlmo_mov_uniq ON vlmo_movimentacoes (
            cnpj_companhia, data_referencia, versao, empresa,
            tipo_cargo, tipo_movimentacao, tipo_ativo, caracteristica,
            data_movimentacao, quantidade);
    """)
    cols = ("cnpj_companhia, data_referencia, versao, empresa, tipo_cargo, tipo_movimentacao, "
            "tipo_ativo, caracteristica, data_movimentacao, quantidade")
    saldo = (PETR, "2026-07-01", 1, "PETROBRAS", "Controlador ou Vinculado", "Saldo Inicial",
             "Ações", "ON", None, 7442231382)
    compra = (PETR, "2026-07-01", 1, "PETROBRAS", "Diretor ou Vinculado", "Compra à vista",
              "Ações", "PN", "2026-07-15", 1000)
    for _ in range(3):
        conn.execute(f"INSERT INTO vlmo_movimentacoes ({cols}) VALUES ({','.join('?' * 10)})", saldo)
    conn.execute(f"INSERT INTO vlmo_movimentacoes ({cols}) VALUES ({','.join('?' * 10)})", compra)
    primeiro_id = conn.execute("SELECT MIN(id) FROM vlmo_movimentacoes").fetchone()[0]
    assert _count(conn) == 4

    _run_sql(conn, MIGRATION)
    assert _count(conn) == 2
    assert conn.execute(
        "SELECT id FROM vlmo_movimentacoes WHERE data_movimentacao IS NULL").fetchone()[0] == primeiro_id

    _run_sql(conn, MIGRATION)  # idempotente
    assert _count(conn) == 2

    # Com o índice novo, a carga casa com as linhas que já estavam lá
    _carga(conn)
    _carga(conn)
    assert _count(conn) == len(LINHAS)
