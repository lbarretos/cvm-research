-- Etapa 6 (docs/proximos-passos/06-linha-economica.md): linha econômica por empresa.
-- Uso: sqlite3 cvm_research.db < scripts/migrations/2026-10-15_linha_economica.sql
--      cd scripts/analysis && python linha_economica.py --full

CREATE TABLE IF NOT EXISTS linha_empresa (
    cnpj_companhia    TEXT NOT NULL,
    tipo_doc          TEXT NOT NULL,
    fonte             TEXT NOT NULL,
    data_referencia   TEXT NOT NULL,
    cd_conta          TEXT NOT NULL,
    linha_id          TEXT NOT NULL,
    ds_conta          TEXT,
    st_conta_fixa     TEXT,              -- 'S' padrão CVM, 'N' criada pela empresa
    casamento         TEXT NOT NULL,     -- primeira | estavel | renumerado | reformulacao | decisao | reatado | reatado_pai | ambiguo | nova
    score             REAL,
    cd_conta_anterior TEXT,              -- conta do filing anterior com a qual casou (ou o candidato, se ambiguo)
    PRIMARY KEY (cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_linha_id ON linha_empresa (cnpj_companhia, tipo_doc, linha_id);

CREATE TABLE IF NOT EXISTS linha_decisao (
    cnpj_companhia TEXT NOT NULL,
    tipo_doc       TEXT NOT NULL,
    cd_a           TEXT NOT NULL,
    data_a         TEXT NOT NULL,
    cd_b           TEXT NOT NULL,
    data_b         TEXT NOT NULL,
    decisao        TEXT NOT NULL CHECK (decisao IN ('mesma', 'diferente')),
    autor          TEXT,
    em             TEXT,
    PRIMARY KEY (cnpj_companhia, tipo_doc, cd_a, data_a, cd_b, data_b)
) WITHOUT ROWID;
