.bail on
-- Acrescenta cd_conta_b/casamento e a flag 'par_ambiguo' a demonstrativos_trimestrais
-- (ver schema.sql). SQLite não altera um CHECK inline, e a tabela é 100% derivada:
-- derrubar e regerar é mais barato e mais seguro que copiar 1,8M linhas.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-18_trimestrais_casamento.sql
--   sqlite3 cvm_research.db < schema.sql
--   cd scripts/analysis && python run_all.py --layer 6 --full
--
-- IMPORTANTE — entre este script e a Camada 6 rodar de novo, a tabela fica VAZIA.
-- Nenhuma query trimestral responde nessa janela; isso é esperado.
-- Os dados descartados eram inválidos: casavam linhas pelo cd_conta, que não é
-- estável entre filings (ver docs/superpowers/plans/2026-09-18-fase6-casamento-de-linhas-no-desacumulo.md).
-- Não é preciso backup: demonstrativos_contabeis, a fonte, não é tocada.
--
-- .bail on é essencial: sem ele uma falha no meio do script não interrompe a execução.

PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS demonstrativos_trimestrais;
PRAGMA foreign_keys = ON;
