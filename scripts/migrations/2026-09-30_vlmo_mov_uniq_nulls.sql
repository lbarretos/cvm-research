.bail on
-- vlmo_mov_uniq passa a ser índice de expressão (IFNULL em cada coluna anulável).
-- Antes, data_movimentacao NULL (todas as linhas 'Saldo Inicial') nunca conflitava
-- na UNIQUE e cada recarga do VLMO inseria os saldos de novo: em 30/09/2026, das
-- 426.773 linhas com data NULL, 339.183 eram cópias (grupos de até 6).
--
-- Uso (na raiz do projeto, com backup feito antes e o código novo de
-- scripts/ingest/utils.py — o ON CONFLICT antigo não casa com o índice novo e o
-- ingest_vlmo.py antigo falha com "ON CONFLICT clause does not match"):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-30_vlmo_mov_uniq_nulls.sql
--
-- Mantém a linha de menor id de cada chave. Dentro de um grupo as cópias só
-- diferem em nome_companhia (espaços que a CVM tirou numa republicação); a
-- próxima carga do ano sobrescreve pelo upsert. Idempotente: rodar de novo não
-- apaga nada e recria o mesmo índice.

BEGIN;

DELETE FROM vlmo_movimentacoes
WHERE id NOT IN (
    SELECT MIN(id) FROM vlmo_movimentacoes
    GROUP BY cnpj_companhia, IFNULL(data_referencia, ''), IFNULL(versao, ''), IFNULL(empresa, ''),
             IFNULL(tipo_cargo, ''), IFNULL(tipo_movimentacao, ''), IFNULL(tipo_ativo, ''),
             IFNULL(caracteristica, ''), IFNULL(data_movimentacao, ''), IFNULL(quantidade, '')
);

DROP INDEX IF EXISTS vlmo_mov_uniq;
CREATE UNIQUE INDEX vlmo_mov_uniq ON vlmo_movimentacoes (
    cnpj_companhia, IFNULL(data_referencia, ''), IFNULL(versao, ''), IFNULL(empresa, ''),
    IFNULL(tipo_cargo, ''), IFNULL(tipo_movimentacao, ''), IFNULL(tipo_ativo, ''),
    IFNULL(caracteristica, ''), IFNULL(data_movimentacao, ''), IFNULL(quantidade, '')
);

COMMIT;
