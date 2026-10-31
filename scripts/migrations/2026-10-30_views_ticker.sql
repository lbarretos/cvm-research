-- Etapa 3 (2026-10-30): `ticker` nas views de DRE, balanço e acionistas, logo depois do CNPJ (JOIN com companies).
-- `WHERE ticker = 'PETR4'` usa idx_companies_ticker (~7 ms) e dispensa o resolve_company antes da consulta.
-- Só views: rápido e sem perda de dado. JOIN interno: filing de empresa fora de companies some das views.

DROP VIEW IF EXISTS vw_dre;
CREATE VIEW IF NOT EXISTS vw_dre AS
SELECT
    f.cnpj_companhia,
    c.ticker,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS receita_liquida,
    MAX(CASE WHEN d.cd_conta = '3.02' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN d.cd_conta = '3.03' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN d.cd_conta = '3.05' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN d.cd_conta = '3.06' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN d.cd_conta = '3.07' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebt,  -- Resultado Antes dos Tributos (3.08 é o IR/CS)
    MAX(CASE WHEN d.cd_conta = '3.11' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS lucro_liquido,
    COALESCE(f.plano_contas, 'padrao') AS plano_contas  -- 'banco' → vw_dre_financeiro; 'seguradora' → vw_dre_seguradora
FROM filings f
JOIN companies c ON c.cnpj = f.cnpj_companhia
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, c.ticker, f.fonte, f.data_referencia;

DROP VIEW IF EXISTS vw_dre_acumulada;
CREATE VIEW IF NOT EXISTS vw_dre_acumulada AS
SELECT
    f.cnpj_companhia,
    c.ticker,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS receita_liquida,
    MAX(CASE WHEN d.cd_conta = '3.02' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN d.cd_conta = '3.03' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN d.cd_conta = '3.05' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN d.cd_conta = '3.06' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN d.cd_conta = '3.07' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS ebt,  -- Resultado Antes dos Tributos (3.08 é o IR/CS)
    MAX(CASE WHEN d.cd_conta = '3.11' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS lucro_liquido,
    COALESCE(f.plano_contas, 'padrao') AS plano_contas  -- 'banco' → vw_dre_financeiro; 'seguradora' → vw_dre_seguradora
FROM filings f
JOIN companies c ON c.cnpj = f.cnpj_companhia
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_min, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, c.ticker, f.fonte, f.data_referencia;

DROP VIEW IF EXISTS vw_dre_financeiro;
CREATE VIEW IF NOT EXISTS vw_dre_financeiro AS
SELECT
    f.cnpj_companhia,
    c.ticker,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01' THEN d.vl_conta END) AS receita_intermediacao,
    MAX(CASE WHEN d.cd_conta = '3.02' THEN d.vl_conta END) AS despesa_intermediacao,
    MAX(CASE WHEN d.cd_conta = '3.03' THEN d.vl_conta END) AS resultado_bruto_intermediacao,
    MAX(CASE WHEN d.cd_conta = '3.04' THEN d.vl_conta END) AS outras_receitas_despesas_operacionais,
    MAX(CASE WHEN d.cd_conta = '3.05' THEN d.vl_conta END) AS lair,
    MAX(CASE WHEN d.cd_conta = '3.06' THEN d.vl_conta END) AS ir_cs,
    CASE WHEN MAX(d.cd_conta = '3.11')
         THEN MAX(CASE WHEN d.cd_conta = '3.11'    THEN d.vl_conta END)
         ELSE MAX(CASE WHEN d.cd_conta = '3.09'    THEN d.vl_conta END) END AS lucro_liquido,
    CASE WHEN MAX(d.cd_conta = '3.11')
         THEN MAX(CASE WHEN d.cd_conta = '3.11.01' THEN d.vl_conta END)
         ELSE MAX(CASE WHEN d.cd_conta = '3.09.01' THEN d.vl_conta END) END AS lucro_controladora
FROM filings f
JOIN companies c ON c.cnpj = f.cnpj_companhia
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE' AND f.plano_contas = 'banco'
GROUP BY f.cnpj_companhia, c.ticker, f.fonte, f.data_referencia;

DROP VIEW IF EXISTS vw_dre_seguradora;
CREATE VIEW IF NOT EXISTS vw_dre_seguradora AS
SELECT
    f.cnpj_companhia,
    c.ticker,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.cd_conta = '3.01'    THEN d.vl_conta END) AS receita_operacoes,
    MAX(CASE WHEN d.cd_conta = '3.02'    THEN d.vl_conta END) AS despesa_operacoes,  -- sinistros e despesas
    MAX(CASE WHEN d.cd_conta = '3.03'    THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN d.cd_conta = '3.04'    THEN d.vl_conta END) AS despesas_administrativas,
    MAX(CASE WHEN d.cd_conta = '3.05'    THEN d.vl_conta END) AS outras_receitas_despesas_operacionais,
    MAX(CASE WHEN d.cd_conta = '3.06'    THEN d.vl_conta END) AS equivalencia_patrimonial,
    MAX(CASE WHEN d.cd_conta = '3.07'    THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN d.cd_conta = '3.08'    THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN d.cd_conta = '3.09'    THEN d.vl_conta END) AS ebt,
    MAX(CASE WHEN d.cd_conta = '3.10'    THEN d.vl_conta END) AS ir_cs,
    MAX(CASE WHEN d.cd_conta = '3.13'    THEN d.vl_conta END) AS lucro_liquido,
    MAX(CASE WHEN d.cd_conta = '3.13.01' THEN d.vl_conta END) AS lucro_controladora
FROM filings f
JOIN companies c ON c.cnpj = f.cnpj_companhia
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE' AND f.plano_contas = 'seguradora'
GROUP BY f.cnpj_companhia, c.ticker, f.fonte, f.data_referencia;

DROP VIEW IF EXISTS vw_balanco;
CREATE VIEW IF NOT EXISTS vw_balanco AS
SELECT
    f.cnpj_companhia,
    c.ticker,
    f.fonte,
    f.data_referencia,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1'       THEN d.vl_conta END) AS ativo_total,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1.01'    AND COALESCE(f.plano_contas, 'padrao') <> 'banco' THEN d.vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1.01.01' AND COALESCE(f.plano_contas, 'padrao') <> 'banco' THEN d.vl_conta END) AS caixa,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.01.04' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.02.01' AND COALESCE(f.plano_contas, 'padrao') = 'padrao' THEN d.vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.03'    AND COALESCE(f.plano_contas, 'padrao') <> 'banco' THEN d.vl_conta END) AS patrimonio_liquido,
    MAX(COALESCE(f.plano_contas, 'padrao')) AS plano_contas
FROM filings f
JOIN companies c ON c.cnpj = f.cnpj_companhia
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
WHERE f.tipo_doc IN ('BPA', 'BPP')
GROUP BY f.cnpj_companhia, c.ticker, f.fonte, f.data_referencia;

DROP VIEW IF EXISTS vw_acionistas_diretos;
CREATE VIEW IF NOT EXISTS vw_acionistas_diretos AS
WITH data_max AS (
    SELECT cnpj_companhia, MAX(data_referencia) AS data_referencia
    FROM fre_posicao_acionaria
    GROUP BY cnpj_companhia
),
versao_max AS (
    SELECT p.cnpj_companhia, p.data_referencia, MAX(p.versao) AS versao
    FROM fre_posicao_acionaria p
    JOIN data_max d
      ON  p.cnpj_companhia  = d.cnpj_companhia
      AND p.data_referencia = d.data_referencia
    GROUP BY p.cnpj_companhia, p.data_referencia
)
SELECT p.cnpj_companhia, c.ticker, p.nome_companhia, p.data_referencia, p.versao,
       p.id_acionista, p.acionista, p.tipo_pessoa_acionista, p.acionista_controlador,
       p.participante_acordo_acionistas,
       p.quantidade_acao_ordinaria_circulacao, p.percentual_acao_ordinaria_circulacao,
       p.quantidade_acao_preferencial_circulacao, p.percentual_acao_preferencial_circulacao,
       p.quantidade_total_acoes_circulacao, p.percentual_total_acoes_circulacao,
       p.data_composicao_capital_social
FROM fre_posicao_acionaria p
JOIN versao_max v
  ON  p.cnpj_companhia  = v.cnpj_companhia
  AND p.data_referencia = v.data_referencia
  AND p.versao          = v.versao
JOIN companies c ON c.cnpj = p.cnpj_companhia
WHERE p.id_acionista_relacionado IS NULL;

