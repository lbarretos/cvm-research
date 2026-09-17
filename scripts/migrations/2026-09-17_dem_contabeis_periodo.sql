-- Reconstrói demonstrativos_contabeis com a chave natural nova (ver schema.sql).
-- SQLite não permite alterar uma UNIQUE inline: cria tabela nova, copia, troca.
-- Uso (na raiz do projeto, com backup feito antes):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-17_dem_contabeis_periodo.sql
--   sqlite3 cvm_research.db < schema.sql      # recria índices e views (IF NOT EXISTS)
-- As linhas existentes são preservadas; st_conta_fixa fica NULL até a reingestão.
PRAGMA foreign_keys = OFF;
BEGIN;

DROP VIEW IF EXISTS vw_dre;
DROP VIEW IF EXISTS vw_dre_acumulada;
DROP VIEW IF EXISTS vw_balanco;

CREATE TABLE demonstrativos_contabeis_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL DEFAULT 1,
    ordem_exercicio TEXT NOT NULL CHECK (ordem_exercicio IN ('Último', 'Penúltimo')),
    dt_ini_exerc    TEXT,
    dt_fim_exerc    TEXT,
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_conta        REAL,
    st_conta_fixa   TEXT CHECK (st_conta_fixa IN ('S', 'N')),
    created_at      TEXT DEFAULT (datetime('now'))
);

INSERT INTO demonstrativos_contabeis_new
    (id, cnpj_companhia, fonte, tipo_doc, data_referencia, versao, ordem_exercicio,
     dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta, created_at)
SELECT id, cnpj_companhia, fonte, tipo_doc, data_referencia, versao, ordem_exercicio,
       dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta, created_at
FROM demonstrativos_contabeis;

DROP TABLE demonstrativos_contabeis;
ALTER TABLE demonstrativos_contabeis_new RENAME TO demonstrativos_contabeis;

COMMIT;
