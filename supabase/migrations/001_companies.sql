-- Tabela mestra de empresas (watchlist)
CREATE TABLE IF NOT EXISTS companies (
    cnpj            TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    codigo_cvm      TEXT,
    nome_cvm        TEXT NOT NULL,
    setor           TEXT,
    status_cvm      TEXT DEFAULT 'ATIVO',
    observacao      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ticker ON companies (ticker);
CREATE INDEX IF NOT EXISTS idx_companies_setor ON companies (setor);
