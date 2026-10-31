"""Bases de teste: cadastra em `companies` a empresa de cada linha inserida em demonstrativos/FRE.

As views de demonstração e de acionistas fazem JOIN com `companies` (coluna `ticker`); numa base real os ingestores
só gravam empresas do watchlist, que ingest_companies.py já cadastrou. Os triggers são TEMP: não entram no
sqlite_master principal, então as comparações de schema com o schema.sql continuam valendo.
"""


def cadastrar_empresas(conn):
    for tabela in ("demonstrativos_contabeis", "fre_posicao_acionaria"):
        conn.execute(
            f"CREATE TEMP TRIGGER IF NOT EXISTS empresa_{tabela} AFTER INSERT ON main.{tabela} BEGIN "
            "INSERT OR IGNORE INTO companies (cnpj, ticker, nome_cvm) "
            "VALUES (NEW.cnpj_companhia, 'T' || substr(replace(replace(replace(NEW.cnpj_companhia, '.', ''), '/', ''), '-', ''), 1, 8), "
            "NEW.cnpj_companhia); END")
    return conn
