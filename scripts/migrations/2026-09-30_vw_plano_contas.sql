.bail on
-- Plano de contas nas views de demonstrativos. vw_dre, vw_dre_acumulada e vw_balanco
-- assumiam o plano padrão e, num banco, devolviam números com outro significado: no
-- DFP 2025 do Itaú, 3.01 "Receitas da Intermediação Financeira" saía como
-- receita_liquida, 3.05 (LAIR) como ebit, 3.07 (operações continuadas) como ebt, e
-- lucro_liquido vinha NULL (o lucro do banco é 3.09). Agora:
--   - vw_plano_contas classifica cada filing em 'padrao' / 'banco' / 'seguradora' pelo
--     nome da conta fixa 3.01 (companies.setor não serve: B3, Itaúsa, Porto Seguro e
--     Caixa Seguridade são 'Financeiro' e publicam no plano padrão);
--   - vw_dre / vw_dre_acumulada devolvem NULL fora do plano padrão e ganham a coluna
--     plano_contas; vw_balanco mantém o que tem o mesmo significado (ativo total; na
--     seguradora também circulante, caixa e PL) e ganha plano_contas;
--   - vw_dre_financeiro (bancos) e vw_dre_seguradora (seguradoras) são novas.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-30_vw_plano_contas.sql
--
-- Só views: nenhum dado é tocado, não precisa de backup nem de reprocessar camadas.
-- Idempotente. As definições abaixo são cópia literal das de schema.sql
-- (tests/test_views_plano_contas.py confere). DROP + CREATE na mesma transação: nenhuma
-- janela sem as views; .bail on faz uma falha abortar antes do COMMIT.

BEGIN;
DROP VIEW IF EXISTS vw_balanco;
DROP VIEW IF EXISTS vw_dre_seguradora;
DROP VIEW IF EXISTS vw_dre_financeiro;
DROP VIEW IF EXISTS vw_dre_acumulada;
DROP VIEW IF EXISTS vw_dre;
DROP VIEW IF EXISTS vw_plano_contas;

-- vw_plano_contas: plano de contas da DRE de cada filing, lido do nome da conta
-- fixa 3.01 (st_conta_fixa = 'S'), que a CVM define por plano:
--   'banco'      — 3.01 "Receitas da/de Intermediação Financeira" (ITUB4, BBAS3, BBDC4, BPAC11)
--   'seguradora' — 3.01 "Receitas das Atividades Seguradoras/Resseguradoras" ou, até 2022,
--                  "Receitas das Operações" (IRBR3, BBSE3)
--   'padrao'     — o resto ("Receita de Venda de Bens e/ou Serviços").
-- Não use companies.setor para isso: B3SA3, ITSA4, CXSE3 e PSSA3 são 'Financeiro' e
-- publicam no plano padrão. Filing sem 3.01 não aparece aqui; as views o tratam como 'padrao'.
CREATE VIEW IF NOT EXISTS vw_plano_contas AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia
)
SELECT
    d.cnpj_companhia,
    d.fonte,
    d.data_referencia,
    CASE
        WHEN MAX(d.ds_conta LIKE '%Intermedia%Financeira%') THEN 'banco'
        WHEN MAX(d.ds_conta LIKE '%Segurador%' OR d.ds_conta = 'Receitas das Operações') THEN 'seguradora'
        ELSE 'padrao'
    END AS plano_contas
FROM demonstrativos_contabeis d
JOIN versao_max v
  ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
  AND d.data_referencia = v.data_referencia AND d.versao = v.versao
WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último' AND d.cd_conta = '3.01'
GROUP BY d.cnpj_companhia, d.fonte, d.data_referencia;

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
    -- fora do plano padrão os códigos querem dizer outra coisa (3.05 é o LAIR de um
    -- banco): a linha fica, com valor NULL
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta,
           COALESCE(pc.plano_contas, 'padrao') AS plano_contas,
           CASE WHEN COALESCE(pc.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END AS vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    JOIN periodo p
      ON  p.cnpj_companhia = d.cnpj_companhia AND p.fonte = d.fonte
      AND p.data_referencia = d.data_referencia
      AND COALESCE(p.dt_ini_exerc, '') = COALESCE(d.dt_ini_exerc, '')
    LEFT JOIN vw_plano_contas pc
      ON  pc.cnpj_companhia = d.cnpj_companhia AND pc.fonte = d.fonte
      AND pc.data_referencia = d.data_referencia
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
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido,
    MAX(plano_contas) AS plano_contas  -- 'banco' → vw_dre_financeiro; 'seguradora' → vw_dre_seguradora
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
    -- fora do plano padrão os códigos querem dizer outra coisa (3.05 é o LAIR de um
    -- banco): a linha fica, com valor NULL
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta,
           COALESCE(pc.plano_contas, 'padrao') AS plano_contas,
           CASE WHEN COALESCE(pc.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END AS vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
      AND d.data_referencia = v.data_referencia AND d.versao = v.versao
    JOIN periodo p
      ON  p.cnpj_companhia = d.cnpj_companhia AND p.fonte = d.fonte
      AND p.data_referencia = d.data_referencia
      AND COALESCE(p.dt_ini_exerc, '') = COALESCE(d.dt_ini_exerc, '')
    LEFT JOIN vw_plano_contas pc
      ON  pc.cnpj_companhia = d.cnpj_companhia AND pc.fonte = d.fonte
      AND pc.data_referencia = d.data_referencia
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
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido,
    MAX(plano_contas) AS plano_contas  -- 'banco' → vw_dre_financeiro; 'seguradora' → vw_dre_seguradora
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

-- vw_dre_financeiro: DRE dos filings no plano de bancos (vw_plano_contas = 'banco'),
-- mesmo período de vw_dre (trimestre isolado no ITR, exercício no DFP). Dois layouts:
--   9 linhas  (ITUB4, BPAC11; BBAS3/BBDC4 até 2019): 3.07 operações continuadas,
--             3.08 descontinuadas, 3.09 lucro do período (3.09.01 controladora)
--   11 linhas (BBAS3/BBDC4 desde 2020): 3.09 lucro antes das participações,
--             3.10 participações nos lucros, 3.11 lucro do período (3.11.01 controladora)
-- O layout de 11 linhas é reconhecido pela presença de 3.11 no filing.
CREATE VIEW IF NOT EXISTS vw_dre_financeiro AS
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
    JOIN vw_plano_contas pc
      ON  pc.cnpj_companhia = d.cnpj_companhia AND pc.fonte = d.fonte
      AND pc.data_referencia = d.data_referencia
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último' AND pc.plano_contas = 'banco'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_ini_exerc) AS dt_ini_exerc,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01' THEN vl_conta END) AS receita_intermediacao,
    MAX(CASE WHEN cd_conta = '3.02' THEN vl_conta END) AS despesa_intermediacao,
    MAX(CASE WHEN cd_conta = '3.03' THEN vl_conta END) AS resultado_bruto_intermediacao,
    MAX(CASE WHEN cd_conta = '3.04' THEN vl_conta END) AS outras_receitas_despesas_operacionais,
    MAX(CASE WHEN cd_conta = '3.05' THEN vl_conta END) AS lair,
    MAX(CASE WHEN cd_conta = '3.06' THEN vl_conta END) AS ir_cs,
    CASE WHEN MAX(cd_conta = '3.11')
         THEN MAX(CASE WHEN cd_conta = '3.11'    THEN vl_conta END)
         ELSE MAX(CASE WHEN cd_conta = '3.09'    THEN vl_conta END) END AS lucro_liquido,
    CASE WHEN MAX(cd_conta = '3.11')
         THEN MAX(CASE WHEN cd_conta = '3.11.01' THEN vl_conta END)
         ELSE MAX(CASE WHEN cd_conta = '3.09.01' THEN vl_conta END) END AS lucro_controladora
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

-- vw_dre_seguradora: DRE dos filings no plano de seguradoras (vw_plano_contas =
-- 'seguradora'; IRBR3, BBSE3), mesmo período de vw_dre. Layout de 13 linhas, igual
-- antes e depois da troca de nomes de 2023 (IFRS 17): 3.07 é o resultado antes do
-- financeiro, 3.09 o antes dos tributos e 3.13 o lucro do período.
CREATE VIEW IF NOT EXISTS vw_dre_seguradora AS
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
    JOIN vw_plano_contas pc
      ON  pc.cnpj_companhia = d.cnpj_companhia AND pc.fonte = d.fonte
      AND pc.data_referencia = d.data_referencia
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último' AND pc.plano_contas = 'seguradora'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_ini_exerc) AS dt_ini_exerc,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01'    THEN vl_conta END) AS receita_operacoes,
    MAX(CASE WHEN cd_conta = '3.02'    THEN vl_conta END) AS despesa_operacoes,  -- sinistros e despesas
    MAX(CASE WHEN cd_conta = '3.03'    THEN vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN cd_conta = '3.04'    THEN vl_conta END) AS despesas_administrativas,
    MAX(CASE WHEN cd_conta = '3.05'    THEN vl_conta END) AS outras_receitas_despesas_operacionais,
    MAX(CASE WHEN cd_conta = '3.06'    THEN vl_conta END) AS equivalencia_patrimonial,
    MAX(CASE WHEN cd_conta = '3.07'    THEN vl_conta END) AS ebit,
    MAX(CASE WHEN cd_conta = '3.08'    THEN vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN cd_conta = '3.09'    THEN vl_conta END) AS ebt,
    MAX(CASE WHEN cd_conta = '3.10'    THEN vl_conta END) AS ir_cs,
    MAX(CASE WHEN cd_conta = '3.13'    THEN vl_conta END) AS lucro_liquido,
    MAX(CASE WHEN cd_conta = '3.13.01' THEN vl_conta END) AS lucro_controladora
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

CREATE VIEW IF NOT EXISTS vw_balanco AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc IN ('BPA', 'BPP') AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.tipo_doc, d.data_referencia,
           d.dt_fim_exerc, d.cd_conta, d.vl_conta,
           COALESCE(pc.plano_contas, 'padrao') AS plano_contas
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia  = v.cnpj_companhia
      AND d.fonte           = v.fonte
      AND d.tipo_doc        = v.tipo_doc
      AND d.data_referencia = v.data_referencia
      AND d.versao          = v.versao
    LEFT JOIN vw_plano_contas pc
      ON  pc.cnpj_companhia = d.cnpj_companhia AND pc.fonte = d.fonte
      AND pc.data_referencia = d.data_referencia
    WHERE d.tipo_doc IN ('BPA', 'BPP') AND d.ordem_exercicio = 'Último'
)
-- Plano do filing pela DRE (vw_plano_contas). O ativo total é '1' em todos os planos.
-- Banco: 1.01 é "Caixa e Equivalentes" e o passivo é aberto por instrumento (2.03 é
-- "Passivos Financeiros ao Custo Amortizado"), então o resto fica NULL. Seguradora:
-- circulante, caixa e PL batem com o padrão; 2.01.04/2.02.01 são provisões técnicas e
-- exigível a longo prazo, não dívida, e ficam NULL.
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1'       THEN vl_conta END) AS ativo_total,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01'    AND plano_contas <> 'banco'  THEN vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01.01' AND plano_contas <> 'banco'  THEN vl_conta END) AS caixa,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.01.04' AND plano_contas = 'padrao'  THEN vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.02.01' AND plano_contas = 'padrao'  THEN vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.03'    AND plano_contas <> 'banco'  THEN vl_conta END) AS patrimonio_liquido,
    MAX(plano_contas) AS plano_contas
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

COMMIT;
