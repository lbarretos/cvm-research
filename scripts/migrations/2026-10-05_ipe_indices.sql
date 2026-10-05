-- Etapa 1 do roadmap (docs/proximos-passos/01-desempenho-e-operacao.md), item 1.4: índices em
-- ipe_docs para as consultas que a skill manda fazer por data_entrega. Antes só existiam
-- índices em data_referencia: `tipo = 'Press-release' AND data_entrega >= ...` levava 5 s e um
-- GROUP BY categoria passava de 40 s.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-10-05_ipe_indices.sql
--
-- Só índices (a construção lê as páginas de metadados, não o texto em overflow); idempotente.
-- Pede o lock de escrita por alguns segundos: rode fora da janela do job semanal.

CREATE INDEX IF NOT EXISTS idx_ipe_tipo_entrega ON ipe_docs (tipo, data_entrega);
CREATE INDEX IF NOT EXISTS idx_ipe_cat_entrega  ON ipe_docs (categoria, data_entrega);
