-- Etapa 7 (docs/proximos-passos/07-taxonomia-canonica.md): conceitos canônicos e fatos padronizados.
-- Uso: sqlite3 cvm_research.db < scripts/migrations/2026-10-16_taxonomia.sql
--      cd scripts/analysis && python taxonomia.py --full   (depende de linha_empresa, Etapa 6)

CREATE TABLE IF NOT EXISTS conceito (
    conceito  TEXT PRIMARY KEY,
    nome      TEXT NOT NULL,
    tipo_doc  TEXT NOT NULL,
    pai       TEXT,
    sinal     INTEGER NOT NULL,
    derivado  INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS linha_conceito (
    cnpj_companhia TEXT NOT NULL,
    tipo_doc       TEXT NOT NULL,
    linha_id       TEXT NOT NULL,
    conceito       TEXT NOT NULL,
    metodo         TEXT NOT NULL,          -- 'regra'
    confianca      REAL NOT NULL,          -- parcela dos votos dos filings classificados
    n_filings      INTEGER NOT NULL,
    PRIMARY KEY (cnpj_companhia, tipo_doc, linha_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS fato_padronizado (
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    periodo_ini     TEXT NOT NULL,         -- 'NA' em balanço
    periodo_fim     TEXT NOT NULL,
    conceito        TEXT NOT NULL,
    valor           REAL,
    n_linhas        INTEGER NOT NULL,
    metodo          TEXT NOT NULL,         -- 'S' | 'regra' | 'derivado'
    confianca       REAL NOT NULL,
    checagem        TEXT NOT NULL,         -- ok | ok_<definição alternativa da DVA> | sem_gabarito | divergente | sinal_trocado | maior_que_pai
    publicado       INTEGER NOT NULL,      -- 1 só se a checagem passou
    PRIMARY KEY (cnpj_companhia, fonte, data_referencia, periodo_ini, periodo_fim, conceito)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_fato_conceito ON fato_padronizado (conceito, data_referencia);
