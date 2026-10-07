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
-- a skill filtra por data_entrega, não por data_referencia
CREATE INDEX IF NOT EXISTS idx_ipe_tipo_entrega ON ipe_docs (tipo, data_entrega);
CREATE INDEX IF NOT EXISTS idx_ipe_cat_entrega  ON ipe_docs (categoria, data_entrega);
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

-- ── Busca por trecho (Etapa 4) ───────────────────────────────────────────────
-- Versões: a mesma chave (empresa, categoria, tipo, espécie, data_referencia, assunto) entregue
-- mais de uma vez; só a de maior data_entrega é a vigente.
CREATE TABLE IF NOT EXISTS ipe_versoes (
    protocolo_entrega TEXT PRIMARY KEY,
    is_latest         INTEGER NOT NULL,
    substituido_por   TEXT
);

-- Um trecho por (empresa, hash do texto normalizado): republicações e FR+CM com o mesmo texto
-- viram uma linha só; ipe_chunk_docs lista os documentos em que ele aparece.
CREATE TABLE IF NOT EXISTS ipe_chunks (
    chunk_id        INTEGER PRIMARY KEY,
    cnpj_companhia  TEXT NOT NULL,
    cnpj_tok        TEXT NOT NULL,      -- só dígitos: o FTS filtra por empresa sem join
    hash            TEXT NOT NULL,
    texto           TEXT NOT NULL,
    rep_protocolo   TEXT NOT NULL,      -- documento mais recente em que o trecho aparece
    rep_ordem       INTEGER NOT NULL,
    categoria       TEXT,
    tipo            TEXT,
    especie         TEXT,
    assunto         TEXT,
    data_entrega    TEXT,
    is_latest       INTEGER NOT NULL DEFAULT 1,   -- aparece em ao menos um documento vigente
    UNIQUE (cnpj_companhia, hash)
);
CREATE INDEX IF NOT EXISTS idx_chunks_rep ON ipe_chunks (rep_protocolo);

CREATE TABLE IF NOT EXISTS ipe_chunk_docs (
    chunk_id          INTEGER NOT NULL,
    protocolo_entrega TEXT NOT NULL,
    ordem             INTEGER NOT NULL,
    PRIMARY KEY (protocolo_entrega, ordem)
);
CREATE INDEX IF NOT EXISTS idx_chunk_docs_chunk ON ipe_chunk_docs (chunk_id);

CREATE VIRTUAL TABLE IF NOT EXISTS ipe_chunks_fts USING fts5(
    texto,
    cnpj_tok,
    content='ipe_chunks',
    content_rowid='chunk_id'
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
-- A UNIQUE é um índice de expressão (IFNULL em cada coluna anulável) porque
-- data_movimentacao é NULL em 'Saldo Inicial' e NULLs são distintos entre si numa
-- UNIQUE comum: cada recarga do VLMO inseria os saldos de novo. O alvo do
-- ON CONFLICT em utils._INDEX_COLUMNS repete estas expressões.
-- Migração: scripts/migrations/2026-09-30_vlmo_mov_uniq_nulls.sql

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
    cnpj_companhia, IFNULL(data_referencia, ''), IFNULL(versao, ''), IFNULL(empresa, ''),
    IFNULL(tipo_cargo, ''), IFNULL(tipo_movimentacao, ''), IFNULL(tipo_ativo, ''),
    IFNULL(caracteristica, ''), IFNULL(data_movimentacao, ''), IFNULL(quantidade, '')
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
    -- ID_Acionista_Relacionado do CSV: NULL = acionista direto da companhia listada;
    -- preenchido = a linha descreve quem detém o acionista de id_acionista = este valor
    -- (cadeia de controle), e os percentuais são do capital desse acionista, não da companhia.
    id_acionista_relacionado                 INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_fre_acionist_relacionado ON fre_posicao_acionaria (cnpj_companhia, data_referencia, versao, id_acionista_relacionado);

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
    vl_conta        REAL,                 -- R$ (MIL×1000); 3.99 (lucro por ação) em R$/ação, sem escala
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

-- Camada 5 (Fase 4): trilha temporal de cada linha (pai + nome) entre filings
-- consecutivos da mesma fonte. Uma linha por mudança (renumerado, reformulacao,
-- ambiguo, nova, removida) ou primeira ocorrência; 'estavel' não é gravada.
-- 'removida' fica no filing em que a linha sumiu, com cd_conta/ds_conta da linha
-- antiga — por isso a UNIQUE inclui classificacao (o código pode ser reutilizado
-- por outra linha no mesmo filing: renumeração em cascata, 15 mil casos).
CREATE TABLE IF NOT EXISTS cd_conta_ds_timeline (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                   TEXT NOT NULL REFERENCES consistency_runs(run_id),
    cnpj_companhia           TEXT NOT NULL,
    tipo_doc                 TEXT NOT NULL,
    cd_conta_pai             TEXT,                 -- NULL no nível 1
    ds_conta_norm            TEXT NOT NULL,        -- normalize_text(ds_conta)
    fonte                    TEXT NOT NULL,
    data_referencia          TEXT NOT NULL,        -- filing B (atual)
    cd_conta                 TEXT NOT NULL,
    ds_conta                 TEXT,
    st_conta_fixa            TEXT,
    data_referencia_anterior TEXT,                 -- filing A (anterior); NULL em primeira_ocorrencia
    cd_conta_anterior        TEXT,
    ds_conta_anterior        TEXT,
    similarity_score         REAL,                 -- 1.0 em renumerado; score em reformulacao/ambiguo
    classificacao            TEXT NOT NULL CHECK (classificacao IN
        ('primeira_ocorrencia','estavel','renumerado','reformulacao','ambiguo','nova','removida')),
    created_at               TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta, classificacao)
);
CREATE INDEX IF NOT EXISTS idx_timeline_chave ON cd_conta_ds_timeline (cnpj_companhia, tipo_doc, cd_conta_pai, ds_conta_norm);
CREATE INDEX IF NOT EXISTS idx_timeline_class ON cd_conta_ds_timeline (classificacao);

-- Camada 6 (Fase 5): valor de cada trimestre da DRE/DFC_MI/DVA por conta e por
-- safra. 'original' = colunas Último; 'reapresentado' = colunas Penúltimo dos
-- filings do exercício seguinte. Os dois operandos de um derivado vêm sempre da
-- mesma safra. Derivado nunca sobrescreve publicado: vl_final = publicado
-- (DRE 1T–3T) ou derivado (4T, DFC_MI, DVA), conforme `origem`.
CREATE TABLE IF NOT EXISTS demonstrativos_trimestrais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES consistency_runs(run_id),
    cnpj_companhia  TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL CHECK (tipo_doc IN ('DRE','DFC_MI','DVA')),
    safra           TEXT NOT NULL CHECK (safra IN ('original','reapresentado')),
    exercicio_ini   TEXT NOT NULL,        -- início do exercício social (dt_ini_exerc do acumulado)
    dt_ini_exerc    TEXT NOT NULL,        -- início do trimestre
    dt_fim_exerc    TEXT NOT NULL,        -- fim do trimestre
    trimestre       INTEGER NOT NULL CHECK (trimestre BETWEEN 1 AND 4),  -- posição no exercício social
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    -- Casamento da linha entre os dois filings (Camada 5, match_filings). Sem eles a
    -- subtração não é auditável: o mesmo cd_conta pode ser outra linha no filing B.
    cd_conta_b      TEXT,                 -- código desta mesma linha no filing B (subtraendo)
    casamento       TEXT CHECK (casamento IN ('estavel','renumerado','reformulacao','ambiguo')),
    vl_publicado    REAL,                 -- linha trimestral do ITR (só DRE 1T–3T)
    vl_derivado     REAL,                 -- acum(Qn) − acum(Qn−1); DFP − acum(3T) no 4T; NULL se não deriva
    origem          TEXT NOT NULL CHECK (origem IN ('publicado','derivado')),
    vl_final        REAL,
    flag            TEXT CHECK (flag IN ('reapresentacao_intra_ano','reclassificacao_entre_filings','componente_reapresentado',
                                         'linha_sem_par','par_ambiguo','sem_anterior','sem_3t','sem_dfp')),
    fonte_a TEXT, data_a TEXT, ordem_a TEXT,   -- filing do minuendo (acumulado do trimestre)
    fonte_b TEXT, data_b TEXT, ordem_b TEXT,   -- filing do subtraendo (NULL no 1T)
    created_at      TEXT DEFAULT (datetime('now')),
    -- exercicio_ini + trimestre, não dt_fim: numa mudança de exercício social o 4T de um
    -- exercício de 12 meses e o 1T do seguinte podem terminar no mesmo dia
    UNIQUE (cnpj_companhia, tipo_doc, safra, exercicio_ini, trimestre, cd_conta)
);
CREATE INDEX IF NOT EXISTS idx_trim_conta ON demonstrativos_trimestrais (cnpj_companhia, tipo_doc, cd_conta, safra, dt_fim_exerc);

-- ── filings: versão vigente e plano de contas de cada documento ───────────────
-- Uma linha por (empresa, fonte, tipo_doc, data_referencia). As views de DRE e balanço
-- leem daqui em vez de recalcular MAX(versao) e o plano de contas sobre a base inteira a
-- cada consulta (o filtro por empresa não descia para essas CTEs: 25 s por empresa).
-- Reconstruída por scripts/ingest/filings.py no fim de ingest_dfp / ingest_itr e no início
-- de run_all.py; nunca edite à mão.
--   versao        maior versão com linhas 'Último' (versão resolvida por documento, não por conta)
--   plano_contas  'padrao' / 'banco' / 'seguradora', lido da DRE e replicado nos cinco tipo_doc
--                 do mesmo (empresa, fonte, data); NULL = filing sem DRE ou sem conta 3.01
--   dt_ini_min    início do acumulado (menor dt_ini_exerc das linhas da versão; NULL em BPA/BPP)
--   dt_ini_max    início do trimestre isolado no ITR (maior dt_ini_exerc); igual a dt_ini_min no DFP
CREATE TABLE IF NOT EXISTS filings (
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL,
    plano_contas    TEXT CHECK (plano_contas IN ('padrao', 'banco', 'seguradora')),
    dt_ini_min      TEXT,
    dt_ini_max      TEXT,
    n_linhas        INTEGER,
    PRIMARY KEY (cnpj_companhia, fonte, tipo_doc, data_referencia)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_filings_fonte_data ON filings (fonte, data_referencia);

-- ── Views ─────────────────────────────────────────────────────────────────────

-- vw_plano_contas: plano de contas da DRE de cada filing, lido do nome da conta
-- fixa 3.01 (st_conta_fixa = 'S'), que a CVM define por plano:
--   'banco'      — 3.01 "Receitas da/de Intermediação Financeira" (ITUB4, BBAS3, BBDC4, BPAC11)
--   'seguradora' — 3.01 "Receitas das Atividades Seguradoras/Resseguradoras" ou, até 2022,
--                  "Receitas das Operações" (IRBR3, BBSE3)
--   'padrao'     — o resto ("Receita de Venda de Bens e/ou Serviços").
-- Não use companies.setor para isso: B3SA3, ITSA4, CXSE3 e PSSA3 são 'Financeiro' e
-- publicam no plano padrão. Filing sem 3.01 não aparece aqui; as views o tratam como 'padrao'.
CREATE VIEW IF NOT EXISTS vw_plano_contas AS
SELECT cnpj_companhia, fonte, data_referencia, plano_contas
FROM filings
WHERE tipo_doc = 'DRE' AND plano_contas IS NOT NULL;

-- vw_dre: DRE do período "curto" de cada filing — trimestre isolado no ITR
-- (dt_ini_exerc mais recente entre as linhas do documento, filings.dt_ini_max) e
-- exercício no DFP. Versão resolvida por documento, não por conta.
-- Fora do plano padrão os códigos querem dizer outra coisa (3.05 é o LAIR de um
-- banco): a linha fica, com valor NULL.
CREATE VIEW IF NOT EXISTS vw_dre AS
SELECT
    f.cnpj_companhia,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS receita_liquida,
    MAX(CASE WHEN d.cd_conta = '3.02' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN d.cd_conta = '3.03' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN d.cd_conta = '3.05' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN d.cd_conta = '3.06' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN d.cd_conta = '3.07' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebt,  -- Resultado Antes dos Tributos (3.08 é o IR/CS)
    MAX(CASE WHEN d.cd_conta = '3.11' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS lucro_liquido,
    COALESCE(f.plano_contas, 'padrao') AS plano_contas  -- 'banco' → vw_dre_financeiro; 'seguradora' → vw_dre_seguradora
FROM filings f
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_dre_acumulada: mesma coisa com o período acumulado no ano (dt_ini_exerc
-- mais antigo, filings.dt_ini_min). No 1T e no DFP coincide com vw_dre.
CREATE VIEW IF NOT EXISTS vw_dre_acumulada AS
SELECT
    f.cnpj_companhia,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS receita_liquida,
    MAX(CASE WHEN d.cd_conta = '3.02' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN d.cd_conta = '3.03' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN d.cd_conta = '3.05' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN d.cd_conta = '3.06' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN d.cd_conta = '3.07' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebt,  -- Resultado Antes dos Tributos (3.08 é o IR/CS)
    MAX(CASE WHEN d.cd_conta = '3.11' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS lucro_liquido,
    COALESCE(f.plano_contas, 'padrao') AS plano_contas  -- 'banco' → vw_dre_financeiro; 'seguradora' → vw_dre_seguradora
FROM filings f
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_min, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_dre_financeiro: DRE dos filings no plano de bancos (filings.plano_contas = 'banco'),
-- mesmo período de vw_dre (trimestre isolado no ITR, exercício no DFP). Dois layouts:
--   9 linhas  (ITUB4, BPAC11; BBAS3/BBDC4 até 2019): 3.07 operações continuadas,
--             3.08 descontinuadas, 3.09 lucro do período (3.09.01 controladora)
--   11 linhas (BBAS3/BBDC4 desde 2020): 3.09 lucro antes das participações,
--             3.10 participações nos lucros, 3.11 lucro do período (3.11.01 controladora)
-- O layout de 11 linhas é reconhecido pela presença de 3.11 no filing.
CREATE VIEW IF NOT EXISTS vw_dre_financeiro AS
SELECT
    f.cnpj_companhia,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01' THEN d.vl_conta END) AS receita_intermediacao,
    MAX(CASE WHEN d.cd_conta = '3.02' THEN d.vl_conta END) AS despesa_intermediacao,
    MAX(CASE WHEN d.cd_conta = '3.03' THEN d.vl_conta END) AS resultado_bruto_intermediacao,
    MAX(CASE WHEN d.cd_conta = '3.04' THEN d.vl_conta END) AS outras_receitas_despesas_operacionais,
    MAX(CASE WHEN d.cd_conta = '3.05' THEN d.vl_conta END) AS lair,
    MAX(CASE WHEN d.cd_conta = '3.06' THEN d.vl_conta END) AS ir_cs,
    CASE WHEN MAX(d.cd_conta = '3.11')
         THEN MAX(CASE WHEN d.cd_conta = '3.11'    THEN d.vl_conta END)
         ELSE MAX(CASE WHEN d.cd_conta = '3.09'    THEN d.vl_conta END) END AS lucro_liquido,
    CASE WHEN MAX(d.cd_conta = '3.11')
         THEN MAX(CASE WHEN d.cd_conta = '3.11.01' THEN d.vl_conta END)
         ELSE MAX(CASE WHEN d.cd_conta = '3.09.01' THEN d.vl_conta END) END AS lucro_controladora
FROM filings f
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE' AND f.plano_contas = 'banco'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_dre_seguradora: DRE dos filings no plano de seguradoras (filings.plano_contas =
-- 'seguradora'; IRBR3, BBSE3), mesmo período de vw_dre. Layout de 13 linhas, igual
-- antes e depois da troca de nomes de 2023 (IFRS 17): 3.07 é o resultado antes do
-- financeiro, 3.09 o antes dos tributos e 3.13 o lucro do período.
CREATE VIEW IF NOT EXISTS vw_dre_seguradora AS
SELECT
    f.cnpj_companhia,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01'    THEN d.vl_conta END) AS receita_operacoes,
    MAX(CASE WHEN d.cd_conta = '3.02'    THEN d.vl_conta END) AS despesa_operacoes,  -- sinistros e despesas
    MAX(CASE WHEN d.cd_conta = '3.03'    THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN d.cd_conta = '3.04'    THEN d.vl_conta END) AS despesas_administrativas,
    MAX(CASE WHEN d.cd_conta = '3.05'    THEN d.vl_conta END) AS outras_receitas_despesas_operacionais,
    MAX(CASE WHEN d.cd_conta = '3.06'    THEN d.vl_conta END) AS equivalencia_patrimonial,
    MAX(CASE WHEN d.cd_conta = '3.07'    THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN d.cd_conta = '3.08'    THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN d.cd_conta = '3.09'    THEN d.vl_conta END) AS ebt,
    MAX(CASE WHEN d.cd_conta = '3.10'    THEN d.vl_conta END) AS ir_cs,
    MAX(CASE WHEN d.cd_conta = '3.13'    THEN d.vl_conta END) AS lucro_liquido,
    MAX(CASE WHEN d.cd_conta = '3.13.01' THEN d.vl_conta END) AS lucro_controladora
FROM filings f
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE' AND f.plano_contas = 'seguradora'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_balanco: BPA + BPP da versão vigente de cada um (filings.versao), plano do filing pela DRE.
-- O ativo total é '1' em todos os planos.
-- Banco: 1.01 é "Caixa e Equivalentes" e o passivo é aberto por instrumento (2.03 é
-- "Passivos Financeiros ao Custo Amortizado"), então o resto fica NULL. Seguradora:
-- circulante, caixa e PL batem com o padrão; 2.01.04/2.02.01 são provisões técnicas e
-- exigível a longo prazo, não dívida, e ficam NULL.
CREATE VIEW IF NOT EXISTS vw_balanco AS
SELECT
    f.cnpj_companhia,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1'       THEN d.vl_conta END) AS ativo_total,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1.01'    AND COALESCE(f.plano_contas, 'padrao') <> 'banco' THEN d.vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1.01.01' AND COALESCE(f.plano_contas, 'padrao') <> 'banco' THEN d.vl_conta END) AS caixa,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.01.04' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.02.01' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.03'    AND COALESCE(f.plano_contas, 'padrao') <> 'banco' THEN d.vl_conta END) AS patrimonio_liquido,
    MAX(COALESCE(f.plano_contas, 'padrao')) AS plano_contas
FROM filings f
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
WHERE f.tipo_doc IN ('BPA', 'BPP')
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_acionistas_diretos: só os acionistas diretos da companhia listada
-- (id_acionista_relacionado NULL), no FRE mais recente de cada empresa
-- (maior data_referencia e, nela, maior versao). As linhas com
-- id_acionista_relacionado preenchido descrevem a cadeia de controle de um
-- acionista e têm percentual sobre o capital DELE; ficam de fora.
-- "Outros" e "Ações Tesouraria" são linhas diretas e entram.
CREATE VIEW IF NOT EXISTS vw_acionistas_diretos AS
WITH data_max AS (
    SELECT cnpj_companhia, MAX(data_referencia) AS data_referencia
    FROM fre_posicao_acionaria
    GROUP BY cnpj_companhia
),
versao_max AS (
    SELECT p.cnpj_companhia, p.data_referencia, MAX(p.versao) AS versao
    FROM fre_posicao_acionaria p
    JOIN data_max d
      ON  p.cnpj_companhia  = d.cnpj_companhia
      AND p.data_referencia = d.data_referencia
    GROUP BY p.cnpj_companhia, p.data_referencia
)
SELECT p.cnpj_companhia, p.nome_companhia, p.data_referencia, p.versao,
       p.id_acionista, p.acionista, p.tipo_pessoa_acionista, p.acionista_controlador,
       p.participante_acordo_acionistas,
       p.quantidade_acao_ordinaria_circulacao, p.percentual_acao_ordinaria_circulacao,
       p.quantidade_acao_preferencial_circulacao, p.percentual_acao_preferencial_circulacao,
       p.quantidade_total_acoes_circulacao, p.percentual_total_acoes_circulacao,
       p.data_composicao_capital_social
FROM fre_posicao_acionaria p
JOIN versao_max v
  ON  p.cnpj_companhia  = v.cnpj_companhia
  AND p.data_referencia = v.data_referencia
  AND p.versao          = v.versao
WHERE p.id_acionista_relacionado IS NULL;
