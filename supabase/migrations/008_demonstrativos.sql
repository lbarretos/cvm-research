-- Demonstrativos contábeis estruturados (DFP anual + ITR trimestral)
-- Fonte: dados.cvm.gov.br — ZIPs anuais filtrados para a watchlist
-- Tipos: BPA, BPP, DRE, DFC_MI, DVA (somente consolidado _con)

CREATE TABLE IF NOT EXISTS demonstrativos_contabeis (
    id              BIGSERIAL PRIMARY KEY,
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,          -- 'DFP' (anual) ou 'ITR' (trimestral)
    tipo_doc        TEXT NOT NULL,          -- 'BPA', 'BPP', 'DRE', 'DFC_MI', 'DVA'
    data_referencia DATE NOT NULL,          -- DT_REFER do documento CVM
    versao          INT  NOT NULL DEFAULT 1, -- VERSAO CVM: 1=original, 2+=reapresentação
    ordem_exercicio TEXT NOT NULL           -- 'Último' (período atual) ou 'Penúltimo' (anterior)
        CHECK (ordem_exercicio IN ('Último', 'Penúltimo')),
    dt_ini_exerc    DATE,                   -- início do período de competência
    dt_fim_exerc    DATE,                   -- fim do período de competência
    cd_conta        TEXT NOT NULL,          -- código CVM ex: '3.01' = Receita Líquida
    ds_conta        TEXT,                   -- descrição da conta
    vl_conta        NUMERIC(22,2),          -- valor normalizado: MIL×1000, UNIDADE×1
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (cnpj_companhia, fonte, tipo_doc, data_referencia, versao, cd_conta, ordem_exercicio)
);

-- Índices para padrões de query esperados
CREATE INDEX IF NOT EXISTS idx_dem_cnpj_fonte
    ON demonstrativos_contabeis (cnpj_companhia, fonte, data_referencia DESC);

CREATE INDEX IF NOT EXISTS idx_dem_tipo_conta
    ON demonstrativos_contabeis (tipo_doc, cd_conta);

CREATE INDEX IF NOT EXISTS idx_dem_cnpj_tipo
    ON demonstrativos_contabeis (cnpj_companhia, tipo_doc, data_referencia DESC);

-- Índice para DISTINCT ON das views (deduplicação por versão mais recente)
CREATE INDEX IF NOT EXISTS idx_dem_versao
    ON demonstrativos_contabeis (cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio, versao DESC);

-- RLS: leitura pública, escrita via service_role (CI jobs)
ALTER TABLE demonstrativos_contabeis ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON demonstrativos_contabeis FOR SELECT USING (true);

-- ── Views ─────────────────────────────────────────────────────────────────────

-- vw_dre: DRE resumida — Último exercício, versão mais recente por período
-- DISTINCT ON deduplica reapresentações: para cada (cnpj, fonte, data_ref, conta, ordem)
-- ordena por versao DESC e pega a primeira linha (versão mais alta = mais recente).
--
-- Limitação: contas CVM padrão para setor real. Bancos/seguradoras (COSIF) retornam NULL.
-- Diagnóstico: SELECT cnpj_companhia FROM vw_dre WHERE receita_liquida IS NULL GROUP BY 1
CREATE OR REPLACE VIEW vw_dre AS
WITH latest AS (
    SELECT DISTINCT ON (cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio)
        cnpj_companhia, fonte, data_referencia, dt_ini_exerc, dt_fim_exerc,
        cd_conta, vl_conta, versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    ORDER BY cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio,
             versao DESC
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    dt_ini_exerc,
    dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01' THEN vl_conta END) AS receita_liquida,
    MAX(CASE WHEN cd_conta = '3.02' THEN vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN cd_conta = '3.03' THEN vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN cd_conta = '3.05' THEN vl_conta END) AS ebit,
    MAX(CASE WHEN cd_conta = '3.06' THEN vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN cd_conta = '3.08' THEN vl_conta END) AS ebt,
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia, dt_ini_exerc, dt_fim_exerc;

-- vw_balanco: BPA + BPP — Último exercício, versão mais recente
-- ASSUME: BPA e BPP do mesmo documento compartilham dt_fim_exerc.
-- Se divergirem, GROUP BY produz linhas separadas (detectável: ativo_total ou
-- patrimonio_liquido = NULL na mesma data_referencia).
CREATE OR REPLACE VIEW vw_balanco AS
WITH latest AS (
    SELECT DISTINCT ON (cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio)
        cnpj_companhia, fonte, tipo_doc, data_referencia, dt_fim_exerc,
        cd_conta, vl_conta, versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc IN ('BPA', 'BPP') AND ordem_exercicio = 'Último'
    ORDER BY cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio,
             versao DESC
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    dt_fim_exerc,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1'       THEN vl_conta END) AS ativo_total,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01'    THEN vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01.01' THEN vl_conta END) AS caixa,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.01.04' THEN vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.02.01' THEN vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.03'    THEN vl_conta END) AS patrimonio_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia, dt_fim_exerc;

-- DVA: armazenada raw, sem view de resumo. Query direta:
--   SELECT cd_conta, ds_conta, vl_conta
--   FROM demonstrativos_contabeis
--   WHERE tipo_doc = 'DVA' AND cnpj_companhia = '...'
--     AND fonte = 'DFP' AND data_referencia = '...' AND ordem_exercicio = 'Último'
--   ORDER BY cd_conta;
