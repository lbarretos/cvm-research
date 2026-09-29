.bail on
-- Acrescenta id_acionista_relacionado a fre_posicao_acionaria (ver schema.sql).
-- O CSV posicao_acionaria do FRE mistura os acionistas diretos da companhia com os
-- acionistas de cada holding da cadeia de controle; ID_Acionista_Relacionado é o que
-- separa os dois (vazio = direto). Sem essa coluna, "maiores acionistas" soma
-- percentuais de entidades diferentes.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-29_fre_acionista_relacionado.sql
--   sqlite3 cvm_research.db < schema.sql      # cria o índice e vw_acionistas_diretos
--   cd scripts/ingest && python ingest_fre.py --desde 2010
--
-- As linhas existentes são APAGADAS: nelas a coluna nova ficaria NULL, que é
-- justamente o valor que marca "acionista direto" — a view devolveria a cadeia
-- inteira como se fosse direta, o erro que esta migração corrige. A tabela é
-- 100% derivada do ZIP do FRE, então a reingestão restaura tudo.
-- IMPORTANTE — entre este script e o ingest_fre.py, fre_posicao_acionaria fica
-- VAZIA; as outras tabelas do FRE não são tocadas.

ALTER TABLE fre_posicao_acionaria ADD COLUMN id_acionista_relacionado INTEGER;
DELETE FROM fre_posicao_acionaria;
