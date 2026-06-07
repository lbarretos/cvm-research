-- CVM Research — SQLite Schema
-- Replaces supabase/migrations/*.sql for local development.
-- Run: sqlite3 cvm_research.db < schema.sql   (or via setup.sh)
-- SQLite ≥ 3.31 required (macOS ships 3.43+).

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── 1. companies ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS companies (
    cnpj            TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    codigo_cvm      TEXT,
    nome_cvm        TEXT NOT NULL,
    setor           TEXT,
    status_cvm      TEXT DEFAULT 'ATIVO',
    observacao      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ticker ON companies (ticker);
CREATE INDEX IF NOT EXISTS idx_companies_setor ON companies (setor);

-- ── 2. ipe_docs ───────────────────────────────────────────────────────────────
-- search_vector (TSVECTOR) removed — use ipe_docs_fts virtual table instead.

CREATE TABLE IF NOT EXISTS ipe_docs (
    protocolo_entrega   TEXT PRIMARY KEY,
    cnpj_companhia      TEXT NOT NULL,
    nome_companhia      TEXT,
    codigo_cvm          TEXT,
    data_referencia     TEXT,
    data_entrega        TEXT,
    categoria           TEXT,
    tipo                TEXT,
    especie             TEXT,
    assunto             TEXT,
    tipo_apresentacao   TEXT,
    versao              INTEGER,
    link_download       TEXT,
    ano                 INTEGER GENERATED ALWAYS AS (
                            CAST(strftime('%Y', data_entrega) AS INTEGER)
                        ) STORED,
    texto_extraido      TEXT,
    extraido_em         TEXT,
    extracao_falhou     INTEGER DEFAULT 0,
    chars_extraidos     INTEGER,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ipe_cnpj_data  ON ipe_docs (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_ipe_categoria  ON ipe_docs (categoria);
CREATE INDEX IF NOT EXISTS idx_ipe_cnpj_cat   ON ipe_docs (cnpj_companhia, categoria, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_ipe_ano        ON ipe_docs (ano);
CREATE INDEX IF NOT EXISTS idx_ipe_sem_texto  ON ipe_docs (cnpj_companhia)
    WHERE texto_extraido IS NULL AND extracao_falhou = 0;

-- FTS5 virtual table for full-text search (external content, manual rebuild).
-- After loading texto_extraido, rebuild with:
--   INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild');
-- Query syntax (different from PostgreSQL tsvector):
--   SELECT i.* FROM ipe_docs_fts f JOIN ipe_docs i USING (protocolo_entrega)
--   WHERE ipe_docs_fts MATCH 'aquisicao AND controle' ORDER BY rank LIMIT 20;
CREATE VIRTUAL TABLE IF NOT EXISTS ipe_docs_fts USING fts5(
    protocolo_entrega,
    cnpj_companhia,
    assunto,
    texto_extraido,
    content='ipe_docs',
    content_rowid='rowid'
);

-- ── 3. vlmo_posicao ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vlmo_posicao (
    protocolo_entrega     TEXT PRIMARY KEY,
    cnpj_companhia        TEXT NOT NULL,
    nome_companhia        TEXT,
    data_referencia       TEXT,
    versao                INTEGER,
    codigo_cvm            TEXT,
    categoria             TEXT,
    tipo                  TEXT,
    data_entrega          TEXT,
    tipo_apresentacao     TEXT,
    motivo_reapresentacao TEXT,
    link_download         TEXT,
    created_at            TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vlmo_pos_cnpj ON vlmo_posicao (cnpj_companhia, data_referencia DESC);

-- ── 4. vlmo_movimentacoes ─────────────────────────────────────────────────────
-- NULLS NOT DISTINCT omitted (not supported in SQLite).
-- Idempotency guaranteed by Python-level dedup in _upsert_sqlite before each batch.

CREATE TABLE IF NOT EXISTS vlmo_movimentacoes (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia         TEXT NOT NULL,
    nome_companhia         TEXT,
    data_referencia        TEXT,
    versao                 INTEGER,
    tipo_empresa           TEXT,
    empresa                TEXT,
    tipo_cargo             TEXT,
    tipo_movimentacao      TEXT,
    descricao_movimentacao TEXT,
    tipo_operacao          TEXT,
    tipo_ativo             TEXT,
    caracteristica         TEXT,
    intermediario          TEXT,
    data_movimentacao      TEXT,
    quantidade             INTEGER,
    preco_unitario         REAL,
    volume                 REAL,
    created_at             TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vlmo_mov_cnpj  ON vlmo_movimentacoes (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_vlmo_mov_cargo ON vlmo_movimentacoes (tipo_cargo);
CREATE INDEX IF NOT EXISTS idx_vlmo_mov_tipo  ON vlmo_movimentacoes (tipo_movimentacao);

CREATE UNIQUE INDEX IF NOT EXISTS vlmo_mov_uniq ON vlmo_movimentacoes (
    cnpj_companhia, data_referencia, versao, empresa,
    tipo_cargo, tipo_movimentacao, tipo_ativo, caracteristica,
    data_movimentacao, quantidade
);

-- ── 5. recompra ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS recompra_programas (
    id_programa                    INTEGER PRIMARY KEY,
    cnpj_companhia                 TEXT NOT NULL,
    nome_companhia                 TEXT,
    quantidade_acoes_ordinarias    INTEGER,
    quantidade_acoes_preferenciais INTEGER,
    finalidade_compra              TEXT,
    data_deliberacao               TEXT,
    motivo                         TEXT,
    data_final_prazo               TEXT,
    situacao                       TEXT,
    created_at                     TEXT DEFAULT (datetime('now')),
    updated_at                     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recompra_cnpj ON recompra_programas (cnpj_companhia, data_deliberacao DESC);

CREATE TABLE IF NOT EXISTS recompra_quantidades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_programa     INTEGER REFERENCES recompra_programas(id_programa),
    cnpj_companhia  TEXT NOT NULL,
    data_referencia TEXT,
    tipo_ativo      TEXT,
    quantidade      INTEGER,
    preco_medio     REAL,
    volume          REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recompra_qtd_cnpj ON recompra_quantidades (cnpj_companhia, data_referencia DESC);

CREATE TABLE IF NOT EXISTS recompra_intermediarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    id_programa    INTEGER REFERENCES recompra_programas(id_programa),
    cnpj_companhia TEXT NOT NULL,
    intermediario  TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);

-- ── 6. fre ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fre_capital_social (
    id                             INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia                 TEXT NOT NULL,
    nome_companhia                 TEXT,
    data_referencia                TEXT,
    versao                         INTEGER,
    id_documento                   INTEGER,
    id_capital_social              INTEGER,
    tipo_capital                   TEXT,
    data_autorizacao_aprovacao     TEXT,
    valor_capital                  REAL,
    quantidade_acoes_ordinarias    INTEGER,
    quantidade_acoes_preferenciais INTEGER,
    quantidade_total_acoes         INTEGER,
    created_at                     TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_capital_social)
);

CREATE INDEX IF NOT EXISTS idx_fre_cap_cnpj ON fre_capital_social (cnpj_companhia, data_referencia DESC);

CREATE TABLE IF NOT EXISTS fre_posicao_acionaria (
    id                                       INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia                           TEXT NOT NULL,
    nome_companhia                           TEXT,
    data_referencia                          TEXT,
    versao                                   INTEGER,
    id_documento                             INTEGER,
    id_acionista                             INTEGER,
    acionista                                TEXT,
    tipo_pessoa_acionista                    TEXT,
    cpf_cnpj_acionista                       TEXT,
    quantidade_acao_ordinaria_circulacao     INTEGER,
    percentual_acao_ordinaria_circulacao     REAL,
    quantidade_acao_preferencial_circulacao  INTEGER,
    percentual_acao_preferencial_circulacao  REAL,
    quantidade_total_acoes_circulacao        INTEGER,
    percentual_total_acoes_circulacao        REAL,
    nacionalidade                            TEXT,
    residente_exterior                       TEXT,
    acionista_controlador                    TEXT,
    participante_acordo_acionistas           TEXT,
    data_composicao_capital_social           TEXT,
    created_at                               TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_acionista)
);

CREATE INDEX IF NOT EXISTS idx_fre_acionist_cnpj        ON fre_posicao_acionaria (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_fre_acionist_controlador ON fre_posicao_acionaria (acionista_controlador);

CREATE TABLE IF NOT EXISTS fre_remuneracao_orgao (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia             TEXT NOT NULL,
    nome_companhia             TEXT,
    data_referencia            TEXT,
    versao                     INTEGER,
    id_documento               INTEGER,
    data_inicio_exercicio      TEXT,
    data_fim_exercicio         TEXT,
    orgao_administracao        TEXT,
    numero_membros             REAL,
    numero_membros_remunerados REAL,
    valor_maior_remuneracao    REAL,
    valor_menor_remuneracao    REAL,
    valor_medio_remuneracao    REAL,
    observacao                 TEXT,
    created_at                 TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_documento, orgao_administracao, data_fim_exercicio)
);

CREATE INDEX IF NOT EXISTS idx_fre_rem_cnpj ON fre_remuneracao_orgao (cnpj_companhia, data_referencia DESC);

-- ── 7. demonstrativos_contabeis ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS demonstrativos_contabeis (
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
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, fonte, tipo_doc, data_referencia, versao, cd_conta, ordem_exercicio)
);

CREATE INDEX IF NOT EXISTS idx_dem_cnpj_fonte ON demonstrativos_contabeis (cnpj_companhia, fonte, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_dem_tipo_conta ON demonstrativos_contabeis (tipo_doc, cd_conta);
CREATE INDEX IF NOT EXISTS idx_dem_cnpj_tipo  ON demonstrativos_contabeis (cnpj_companhia, tipo_doc, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_dem_versao     ON demonstrativos_contabeis (cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio, versao DESC);

-- ── Views ─────────────────────────────────────────────────────────────────────
-- DISTINCT ON (PostgreSQL) replaced by MAX(versao) CTE — semantically equivalent.

CREATE VIEW IF NOT EXISTS vw_dre AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, cd_conta, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia, cd_conta
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia  = v.cnpj_companhia
      AND d.fonte           = v.fonte
      AND d.data_referencia = v.data_referencia
      AND d.cd_conta        = v.cd_conta
      AND d.versao          = v.versao
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_ini_exerc) AS dt_ini_exerc,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01' THEN vl_conta END) AS receita_liquida,
    MAX(CASE WHEN cd_conta = '3.02' THEN vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN cd_conta = '3.03' THEN vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN cd_conta = '3.05' THEN vl_conta END) AS ebit,
    MAX(CASE WHEN cd_conta = '3.06' THEN vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN cd_conta = '3.08' THEN vl_conta END) AS ebt,
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

CREATE VIEW IF NOT EXISTS vw_balanco AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc IN ('BPA', 'BPP') AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.tipo_doc, d.data_referencia,
           d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia  = v.cnpj_companhia
      AND d.fonte           = v.fonte
      AND d.tipo_doc        = v.tipo_doc
      AND d.data_referencia = v.data_referencia
      AND d.cd_conta        = v.cd_conta
      AND d.versao          = v.versao
    WHERE d.tipo_doc IN ('BPA', 'BPP') AND d.ordem_exercicio = 'Último'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1'       THEN vl_conta END) AS ativo_total,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01'    THEN vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01.01' THEN vl_conta END) AS caixa,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.01.04' THEN vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.02.01' THEN vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.03'    THEN vl_conta END) AS patrimonio_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;
