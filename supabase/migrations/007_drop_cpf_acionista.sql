-- Remove CPF de pessoas físicas da tabela de composição acionária (LGPD).
-- Nome e percentual do acionista são suficientes para análise de research.
ALTER TABLE fre_posicao_acionaria DROP COLUMN IF EXISTS cpf_cnpj_acionista;
