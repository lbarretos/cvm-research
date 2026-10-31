.bail on
-- Acrescenta casamento 'decisao' ao CHECK de demonstrativos_trimestrais.casamento: a Camada 6 passa a ler
-- linha_decisao ('mesma' casa o par ambíguo e deriva o valor; 'diferente' desfaz o casamento). SQLite não altera
-- um CHECK inline e a tabela é 100% derivada: derrubar e regerar, como na migração de 2026-09-30.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-10-30_trimestrais_decisao.sql
--   sqlite3 cvm_research.db < schema.sql
--   cd scripts/analysis && python run_all.py --layer 6 --full
--
-- Entre este script e a Camada 6 rodar de novo, a tabela fica VAZIA. A Camada 6 nova se recusa a rodar sem esta
-- migração (antes de apagar qualquer linha). demonstrativos_contabeis, a fonte, não é tocada.

PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS demonstrativos_trimestrais;
PRAGMA foreign_keys = ON;
