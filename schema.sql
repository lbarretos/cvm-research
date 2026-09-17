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

-- Chave natural inclui o período (dt_ini_exerc): no ITR de 2T/3T a CVM publica
-- cada conta da DRE duas vezes (trimestre isolado e acumulado no ano). Sem
-- dt_ini_exerc na chave, o upsert guardava uma das duas por acaso.
-- A UNIQUE é um índice de expressão porque dt_ini_exerc é NULL em BPA/BPP e
-- NULLs são distintos entre si numa UNIQUE comum (o upsert nunca conflitaria).
CREATE TABLE IF NOT EXISTS demonstrativos_contabeis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL DEFAULT 1,
    ordem_exercicio TEXT NOT NULL CHECK (ordem_exercicio IN ('Último', 'Penúltimo')),
    dt_ini_exerc    TEXT,                 -- NULL em BPA/BPP (posição, não fluxo)
    dt_fim_exerc    TEXT,
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_conta        REAL,
    st_conta_fixa   TEXT CHECK (st_conta_fixa IN ('S', 'N')),  -- S = conta padrão CVM, N = criada pela empresa; NULL = linha anterior à migração 2026-09-17
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dem_periodo ON demonstrativos_contabeis
    (cnpj_companhia, fonte, tipo_doc, data_referencia, versao, cd_conta, ordem_exercicio, COALESCE(dt_ini_exerc, ''));

CREATE INDEX IF NOT EXISTS idx_dem_cnpj_fonte ON demonstrativos_contabeis (cnpj_companhia, fonte, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_dem_tipo_conta ON demonstrativos_contabeis (tipo_doc, cd_conta);
CREATE INDEX IF NOT EXISTS idx_dem_cnpj_tipo  ON demonstrativos_contabeis (cnpj_companhia, tipo_doc, data_referencia DESC);

-- ── Notas Explicativas (ITR/DFP) ────────────────────────────────────────────
-- Texto completo extraído do PDF oficial do ITR/DFP (o mesmo documento
-- publicado em RI). Não existe em demonstrativos_contabeis: aquela tabela só
-- tem os quadros padronizados (BPA/BPP/DRE/DFC_MI/DVA), sem notas.
-- Ver scripts/ingest/ingest_notas_explicativas.py para o fluxo de extração.

CREATE TABLE IF NOT EXISTS notas_explicativas (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia               TEXT NOT NULL,
    fonte                        TEXT NOT NULL CHECK (fonte IN ('ITR', 'DFP')),
    data_referencia              TEXT NOT NULL,
    versao                       INTEGER NOT NULL DEFAULT 1,
    numero_sequencial_documento  INTEGER NOT NULL,
    link_download                TEXT,
    texto_extraido               TEXT,
    extraido_em                  TEXT,
    extracao_falhou              INTEGER DEFAULT 0,
    chars_extraidos              INTEGER,
    created_at                   TEXT DEFAULT (datetime('now')),
    updated_at                   TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, fonte, data_referencia)
);

CREATE INDEX IF NOT EXISTS idx_notas_cnpj_data ON notas_explicativas (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_notas_sem_texto ON notas_explicativas (cnpj_companhia)
    WHERE texto_extraido IS NULL AND extracao_falhou = 0;

-- Busca full-text (idêntico ao padrão de ipe_docs_fts):
--   INSERT INTO notas_explicativas_fts(notas_explicativas_fts) VALUES ('rebuild');
--   SELECT n.* FROM notas_explicativas_fts f JOIN notas_explicativas n ON n.id = f.rowid
--   WHERE notas_explicativas_fts MATCH 'imobilizado AND depreciacao' ORDER BY rank LIMIT 20;
CREATE VIRTUAL TABLE IF NOT EXISTS notas_explicativas_fts USING fts5(
    cnpj_companhia,
    texto_extraido,
    content='notas_explicativas',
    content_rowid='id'
);

-- ── 8. Consistência de dados financeiros ─────────────────────────────────────
-- Achados dos scripts de scripts/analysis/ (rodam no job semanal após DFP/ITR). Nunca alteram
-- demonstrativos_contabeis: o valor publicado pela CVM é intocável; aqui ficam
-- os metadados (reapresentação, reclassificação, etc.) linha a linha.
-- Camadas: 2 = cruzamento entre filings (Fase 1); 1 = soma hierárquica (Fase 2);
-- 3 = granularidade (Fase 3); 4/5 = texto (Fase 4); 6 = desacúmulo (Fase 5).

CREATE TABLE IF NOT EXISTS consistency_runs (
    run_id          TEXT PRIMARY KEY,
    layer           INTEGER NOT NULL,      -- 1, 2, 3, 5, 6
    check_type      TEXT NOT NULL,         -- ex: 'cross_period'
    escopo          TEXT,                  -- 'full' ou 'cnpj=... tipo_doc=... desde=... ate=...'
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    total_checked   INTEGER,               -- unidades checadas (Camada 2: pares documento×período)
    total_flagged   INTEGER,
    script_args     TEXT                   -- JSON dos argumentos do script
);

-- Uma flag por linha divergente; linhas com cd_conta NULL são o resumo do par
-- de documentos (detalhe JSON com contagens). Flags são substituídas por
-- (layer, check_type, cnpj_companhia[, tipo_doc]) a cada execução — a tabela
-- reflete sempre a última execução de cada escopo; o histórico fica em runs.
CREATE TABLE IF NOT EXISTS consistency_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES consistency_runs(run_id),
    layer           INTEGER NOT NULL,
    check_type      TEXT NOT NULL,
    classificacao   TEXT NOT NULL,         -- Camada 2: 'reapresentacao' | 'reclassificacao'
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'error')),
    cnpj_companhia  TEXT NOT NULL,
    tipo_doc        TEXT,
    cd_conta        TEXT,                  -- NULL = resumo do par de documentos
    cd_conta_pai    TEXT,
    ds_conta        TEXT,
    periodo_ini     TEXT,                  -- COALESCE(dt_ini_exerc, 'NA')
    periodo_fim     TEXT,                  -- dt_fim_exerc
    fonte_ref       TEXT,  data_ref  TEXT, ordem_ref  TEXT,   -- filing de referência (baseline)
    fonte_cmp       TEXT,  data_cmp  TEXT, ordem_cmp  TEXT,   -- filing comparado
    valor_ref       REAL,
    valor_cmp       REAL,
    diff_abs        REAL,                  -- valor_cmp − valor_ref
    diff_rel        REAL,                  -- diff_abs / |valor_ref| (NULL se valor_ref = 0)
    detalhe         TEXT,                  -- JSON livre
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cflags_cnpj  ON consistency_flags (cnpj_companhia, periodo_fim DESC);
CREATE INDEX IF NOT EXISTS idx_cflags_class ON consistency_flags (layer, classificacao, severity);
CREATE INDEX IF NOT EXISTS idx_cflags_run   ON consistency_flags (run_id);

-- ── Views ─────────────────────────────────────────────────────────────────────
-- DISTINCT ON (PostgreSQL) replaced by MAX(versao) CTE — semantically equivalent.

-- vw_dre: DRE do período "curto" de cada filing — trimestre isolado no ITR
-- (dt_ini_exerc mais recente entre as linhas do documento) e exercício no DFP.
-- Versão resolvida por documento, não por conta.
CREATE VIEW IF NOT EXISTS vw_dre AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia
),
periodo AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia, MAX(d.dt_ini_exerc) AS dt_ini_exerc
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
    GROUP BY d.cnpj_companhia, d.fonte, d.data_referencia
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    JOIN periodo p
      ON  p.cnpj_companhia = d.cnpj_companhia AND p.fonte = d.fonte
      AND p.data_referencia = d.data_referencia
      AND COALESCE(p.dt_ini_exerc, '') = COALESCE(d.dt_ini_exerc, '')
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

-- vw_dre_acumulada: mesma coisa com o período acumulado no ano (dt_ini_exerc
-- mais antigo). No 1T e no DFP coincide com vw_dre.
CREATE VIEW IF NOT EXISTS vw_dre_acumulada AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia
),
periodo AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia, MIN(d.dt_ini_exerc) AS dt_ini_exerc
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
    GROUP BY d.cnpj_companhia, d.fonte, d.data_referencia
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    JOIN periodo p
      ON  p.cnpj_companhia = d.cnpj_companhia AND p.fonte = d.fonte
      AND p.data_referencia = d.data_referencia
      AND COALESCE(p.dt_ini_exerc, '') = COALESCE(d.dt_ini_exerc, '')
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
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc IN ('BPA', 'BPP') AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia
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
