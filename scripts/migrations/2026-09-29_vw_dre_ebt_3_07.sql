.bail on
-- Corrige `ebt` em vw_dre e vw_dre_acumulada: apontava para 3.08 (Imposto de Renda e
-- Contribuição Social sobre o Lucro) em vez de 3.07 (Resultado Antes dos Tributos sobre
-- o Lucro). Ex.: WEG ITR 2026-06-30, trimestre isolado — 3.07 = 1.982.192.000,
-- 3.08 = -335.648.000; a view devolvia -335.648.000 como EBT.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-29_vw_dre_ebt_3_07.sql
--
-- Só views: nenhum dado é tocado, não precisa de backup nem de reprocessar camadas.
-- Idempotente. As definições abaixo são cópia literal das de schema.sql
-- (tests/test_ingest_periodo.py confere). DROP + CREATE na mesma transação: nenhuma
-- janela sem as views; .bail on faz uma falha abortar antes do COMMIT.

BEGIN;
DROP VIEW IF EXISTS vw_dre;
DROP VIEW IF EXISTS vw_dre_acumulada;

-- vw_dre: DRE do período "curto" de cada filing — trimestre isolado no ITR
-- (dt_ini_exerc mais recente entre as linhas do documento) e exercício no DFP.
-- Versão resolvida por documento, não por conta.
CREATE VIEW IF NOT EXISTS vw_dre AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia
),
periodo AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia, MAX(d.dt_ini_exerc) AS dt_ini_exerc
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
    GROUP BY d.cnpj_companhia, d.fonte, d.data_referencia
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    JOIN periodo p
      ON  p.cnpj_companhia = d.cnpj_companhia AND p.fonte = d.fonte
      AND p.data_referencia = d.data_referencia
      AND COALESCE(p.dt_ini_exerc, '') = COALESCE(d.dt_ini_exerc, '')
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_ini_exerc) AS dt_ini_exerc,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01' THEN vl_conta END) AS receita_liquida,
    MAX(CASE WHEN cd_conta = '3.02' THEN vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN cd_conta = '3.03' THEN vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN cd_conta = '3.05' THEN vl_conta END) AS ebit,
    MAX(CASE WHEN cd_conta = '3.06' THEN vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN cd_conta = '3.07' THEN vl_conta END) AS ebt,  -- Resultado Antes dos Tributos (3.08 é o IR/CS)
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

-- vw_dre_acumulada: mesma coisa com o período acumulado no ano (dt_ini_exerc
-- mais antigo). No 1T e no DFP coincide com vw_dre.
CREATE VIEW IF NOT EXISTS vw_dre_acumulada AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia
),
periodo AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia, MIN(d.dt_ini_exerc) AS dt_ini_exerc
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
    GROUP BY d.cnpj_companhia, d.fonte, d.data_referencia
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    JOIN periodo p
      ON  p.cnpj_companhia = d.cnpj_companhia AND p.fonte = d.fonte
      AND p.data_referencia = d.data_referencia
      AND COALESCE(p.dt_ini_exerc, '') = COALESCE(d.dt_ini_exerc, '')
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_ini_exerc) AS dt_ini_exerc,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01' THEN vl_conta END) AS receita_liquida,
    MAX(CASE WHEN cd_conta = '3.02' THEN vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN cd_conta = '3.03' THEN vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN cd_conta = '3.05' THEN vl_conta END) AS ebit,
    MAX(CASE WHEN cd_conta = '3.06' THEN vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN cd_conta = '3.07' THEN vl_conta END) AS ebt,  -- Resultado Antes dos Tributos (3.08 é o IR/CS)
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

COMMIT;
