-- Etapa 9, Bloco B (docs/proximos-passos/09-busca-em-documentos.md): métrica de qualidade do texto por página.
-- Uso: sqlite3 cvm_research.db < scripts/migrations/2026-11-09_ipe_docs_qualidade.sql
--      cd scripts/ingest && python backfill_qualidade.py       # preenche
ALTER TABLE ipe_docs ADD COLUMN qualidade TEXT;
ALTER TABLE ipe_docs ADD COLUMN texto_qualidade TEXT;
CREATE INDEX IF NOT EXISTS idx_ipe_docs_qualidade ON ipe_docs (qualidade) WHERE qualidade IS NOT NULL;
