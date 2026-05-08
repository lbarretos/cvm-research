-- Catálogo de documentos IPE (metadados + texto extraído)
CREATE TABLE IF NOT EXISTS ipe_docs (
    protocolo_entrega   TEXT PRIMARY KEY,
    cnpj_companhia      TEXT NOT NULL,
    nome_companhia      TEXT,
    codigo_cvm          TEXT,
    data_referencia     DATE,
    data_entrega        DATE,
    categoria           TEXT,   -- 'Fato Relevante', 'Assembleia', 'Comunicado ao Mercado'...
    tipo                TEXT,   -- 'AGO', 'AGE', etc.
    especie             TEXT,
    assunto             TEXT,
    tipo_apresentacao   TEXT,   -- 'AP - Apresentação', 'RE - Reapresentação Espontânea'
    versao              INT,
    link_download       TEXT,
    ano                 INT GENERATED ALWAYS AS (EXTRACT(YEAR FROM data_entrega)::INT) STORED,

    -- Conteúdo extraído do PDF
    texto_extraido      TEXT,
    extraido_em         TIMESTAMPTZ,
    extracao_falhou     BOOLEAN DEFAULT FALSE,
    chars_extraidos     INT,

    -- Full-text search
    search_vector       TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('portuguese', COALESCE(assunto, '')), 'A') ||
        setweight(to_tsvector('portuguese', COALESCE(texto_extraido, '')), 'B')
    ) STORED,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para os padrões de consulta mais comuns
CREATE INDEX IF NOT EXISTS idx_ipe_cnpj_data     ON ipe_docs (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_ipe_categoria      ON ipe_docs (categoria);
CREATE INDEX IF NOT EXISTS idx_ipe_cnpj_cat       ON ipe_docs (cnpj_companhia, categoria, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_ipe_ano            ON ipe_docs (ano);
CREATE INDEX IF NOT EXISTS idx_ipe_sem_texto      ON ipe_docs (cnpj_companhia) WHERE texto_extraido IS NULL AND extracao_falhou = FALSE;
CREATE INDEX IF NOT EXISTS idx_ipe_fts            ON ipe_docs USING GIN (search_vector);
