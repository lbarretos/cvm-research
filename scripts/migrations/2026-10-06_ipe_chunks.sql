-- Etapa 4 do roadmap (docs/proximos-passos/04-texto-e-busca.md): busca por trecho.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-10-06_ipe_chunks.sql
--   cd scripts/ingest && python build_chunks.py        # preenche (~10 min na camada quente)
--
-- Só cria tabelas novas (nada em ipe_docs é alterado, então não reescreve o texto). Idempotente.

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
