.bail on
-- Acrescenta a flag 'reclassificacao_entre_filings' ao CHECK de demonstrativos_trimestrais.flag
-- (ver schema.sql e o docstring de scripts/analysis/derive_quarters.py). SQLite não altera um
-- CHECK inline, e a tabela é 100% derivada: derrubar e regerar é mais barato e mais seguro que
-- copiar 1,8M linhas.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-30_trimestrais_reclassificacao.sql
--   sqlite3 cvm_research.db < schema.sql
--   cd scripts/analysis && python run_all.py --layer 6 --full
--
-- IMPORTANTE — entre este script e a Camada 6 rodar de novo, a tabela fica VAZIA.
-- Nenhuma query trimestral responde nessa janela; isso é esperado. A Camada 6 nova se recusa a
-- rodar num banco sem esta migração (antes de apagar qualquer linha), então o job semanal não
-- deixa a tabela pela metade: falha no passo consistency_l6 até a migração ser aplicada.
-- Não é preciso backup: demonstrativos_contabeis, a fonte, não é tocada.
--
-- .bail on é essencial: sem ele uma falha no meio do script não interrompe a execução.

PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS demonstrativos_trimestrais;
PRAGMA foreign_keys = ON;
