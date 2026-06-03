-- Documenta o índice único de movimentações VLMO que existia no banco mas
-- não constava nas migrations anteriores.
-- O CSV da CVM publica linhas duplicadas sob esta chave; o ingestor deduplica
-- antes do upsert, e esta constraint garante idempotência no banco.
CREATE UNIQUE INDEX IF NOT EXISTS vlmo_mov_uniq
    ON public.vlmo_movimentacoes (
        cnpj_companhia, data_referencia, versao, empresa,
        tipo_cargo, tipo_movimentacao, tipo_ativo, caracteristica,
        data_movimentacao, quantidade
    ) NULLS NOT DISTINCT;
