.bail on
-- Etapa 1 do roadmap (docs/proximos-passos/01-desempenho-e-operacao.md): tabela `filings` e
-- views de DRE/balanço reescritas para lê-la. As views antigas calculavam MAX(versao) e o plano
-- de contas sobre a base inteira antes de aplicar o filtro por empresa (vw_balanco de uma empresa:
-- 24,8 s no banco vivo, e o MCP aborta em 20 s); as novas fazem uma junção pela chave completa
-- (3 ms por empresa). O resultado é idêntico: tests/test_filings.py compara as duas definições
-- linha a linha.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-10-05_filings_views.sql
--
-- Cria e preenche `filings` (~4 s) e troca as views na mesma transação, então não há janela sem
-- view nem view lendo tabela vazia. Nenhum dado de demonstrativos_contabeis é tocado: não precisa
-- de backup nem de reprocessar camadas. Idempotente. As definições abaixo são cópia literal de
-- schema.sql e o preenchimento é cópia de scripts/ingest/filings.py (REBUILD_SQL); os testes conferem.
-- Depois desta migração, ingest_dfp/ingest_itr e run_all.py mantêm `filings` atualizada.

BEGIN;

-- ── filings: versão vigente e plano de contas de cada documento ───────────────
-- Uma linha por (empresa, fonte, tipo_doc, data_referencia). As views de DRE e balanço
-- leem daqui em vez de recalcular MAX(versao) e o plano de contas sobre a base inteira a
-- cada consulta (o filtro por empresa não descia para essas CTEs: 25 s por empresa).
-- Reconstruída por scripts/ingest/filings.py no fim de ingest_dfp / ingest_itr e no início
-- de run_all.py; nunca edite à mão.
--   versao        maior versão com linhas 'Último' (versão resolvida por documento, não por conta)
--   plano_contas  'padrao' / 'banco' / 'seguradora', lido da DRE e replicado nos cinco tipo_doc
--                 do mesmo (empresa, fonte, data); NULL = filing sem DRE ou sem conta 3.01
--   dt_ini_min    início do acumulado (menor dt_ini_exerc das linhas da versão; NULL em BPA/BPP)
--   dt_ini_max    início do trimestre isolado no ITR (maior dt_ini_exerc); igual a dt_ini_min no DFP
CREATE TABLE IF NOT EXISTS filings (
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL,
    plano_contas    TEXT CHECK (plano_contas IN ('padrao', 'banco', 'seguradora')),
    dt_ini_min      TEXT,
    dt_ini_max      TEXT,
    n_linhas        INTEGER,
    PRIMARY KEY (cnpj_companhia, fonte, tipo_doc, data_referencia)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_filings_fonte_data ON filings (fonte, data_referencia);

DELETE FROM filings;

INSERT INTO filings (cnpj_companhia, fonte, tipo_doc, data_referencia, versao)
SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao)
FROM demonstrativos_contabeis
WHERE ordem_exercicio = 'Último'
GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia;

UPDATE filings SET
  (dt_ini_min, dt_ini_max, n_linhas) = (
    SELECT MIN(d.dt_ini_exerc), MAX(d.dt_ini_exerc), COUNT(*) FROM demonstrativos_contabeis d
    WHERE d.cnpj_companhia = filings.cnpj_companhia AND d.fonte = filings.fonte
      AND d.tipo_doc = filings.tipo_doc AND d.data_referencia = filings.data_referencia
      AND d.versao = filings.versao AND d.ordem_exercicio = 'Último');

-- Plano lido do nome da conta fixa 3.01 da DRE e replicado nos demais tipo_doc do mesmo
-- (cnpj, fonte, data). NULL = filing sem DRE ou sem 3.01 (as views o tratam como 'padrao').
UPDATE filings SET plano_contas = (
    SELECT CASE WHEN MAX(d.ds_conta LIKE '%Intermedia%Financeira%') THEN 'banco'
                WHEN MAX(d.ds_conta LIKE '%Segurador%' OR d.ds_conta = 'Receitas das Operações') THEN 'seguradora'
                ELSE 'padrao' END
    FROM filings f JOIN demonstrativos_contabeis d
      ON d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
     AND d.data_referencia = f.data_referencia AND d.versao = f.versao
    WHERE f.cnpj_companhia = filings.cnpj_companhia AND f.fonte = filings.fonte
      AND f.data_referencia = filings.data_referencia AND f.tipo_doc = 'DRE'
      AND d.ordem_exercicio = 'Último' AND d.cd_conta = '3.01'
    HAVING COUNT(*) > 0);

DROP VIEW IF EXISTS vw_balanco;
DROP VIEW IF EXISTS vw_dre_seguradora;
DROP VIEW IF EXISTS vw_dre_financeiro;
DROP VIEW IF EXISTS vw_dre_acumulada;
DROP VIEW IF EXISTS vw_dre;
DROP VIEW IF EXISTS vw_plano_contas;

-- ── Views ─────────────────────────────────────────────────────────────────────

-- vw_plano_contas: plano de contas da DRE de cada filing, lido do nome da conta
-- fixa 3.01 (st_conta_fixa = 'S'), que a CVM define por plano:
--   'banco'      — 3.01 "Receitas da/de Intermediação Financeira" (ITUB4, BBAS3, BBDC4, BPAC11)
--   'seguradora' — 3.01 "Receitas das Atividades Seguradoras/Resseguradoras" ou, até 2022,
--                  "Receitas das Operações" (IRBR3, BBSE3)
--   'padrao'     — o resto ("Receita de Venda de Bens e/ou Serviços").
-- Não use companies.setor para isso: B3SA3, ITSA4, CXSE3 e PSSA3 são 'Financeiro' e
-- publicam no plano padrão. Filing sem 3.01 não aparece aqui; as views o tratam como 'padrao'.
CREATE VIEW IF NOT EXISTS vw_plano_contas AS
SELECT cnpj_companhia, fonte, data_referencia, plano_contas
FROM filings
WHERE tipo_doc = 'DRE' AND plano_contas IS NOT NULL;

-- vw_dre: DRE do período "curto" de cada filing — trimestre isolado no ITR
-- (dt_ini_exerc mais recente entre as linhas do documento, filings.dt_ini_max) e
-- exercício no DFP. Versão resolvida por documento, não por conta.
-- Fora do plano padrão os códigos querem dizer outra coisa (3.05 é o LAIR de um
-- banco): a linha fica, com valor NULL.
CREATE VIEW IF NOT EXISTS vw_dre AS
SELECT
    f.cnpj_companhia,
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
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_dre_acumulada: mesma coisa com o período acumulado no ano (dt_ini_exerc
-- mais antigo, filings.dt_ini_min). No 1T e no DFP coincide com vw_dre.
CREATE VIEW IF NOT EXISTS vw_dre_acumulada AS
SELECT
    f.cnpj_companhia,
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
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_min, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_dre_financeiro: DRE dos filings no plano de bancos (filings.plano_contas = 'banco'),
-- mesmo período de vw_dre (trimestre isolado no ITR, exercício no DFP). Dois layouts:
--   9 linhas  (ITUB4, BPAC11; BBAS3/BBDC4 até 2019): 3.07 operações continuadas,
--             3.08 descontinuadas, 3.09 lucro do período (3.09.01 controladora)
--   11 linhas (BBAS3/BBDC4 desde 2020): 3.09 lucro antes das participações,
--             3.10 participações nos lucros, 3.11 lucro do período (3.11.01 controladora)
-- O layout de 11 linhas é reconhecido pela presença de 3.11 no filing.
CREATE VIEW IF NOT EXISTS vw_dre_financeiro AS
SELECT
    f.cnpj_companhia,
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
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE' AND f.plano_contas = 'banco'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_dre_seguradora: DRE dos filings no plano de seguradoras (filings.plano_contas =
-- 'seguradora'; IRBR3, BBSE3), mesmo período de vw_dre. Layout de 13 linhas, igual
-- antes e depois da troca de nomes de 2023 (IFRS 17): 3.07 é o resultado antes do
-- financeiro, 3.09 o antes dos tributos e 3.13 o lucro do período.
CREATE VIEW IF NOT EXISTS vw_dre_seguradora AS
SELECT
    f.cnpj_companhia,
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
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
  AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE' AND f.plano_contas = 'seguradora'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

-- vw_balanco: BPA + BPP da versão vigente de cada um (filings.versao), plano do filing pela DRE.
-- O ativo total é '1' em todos os planos.
-- Banco: 1.01 é "Caixa e Equivalentes" e o passivo é aberto por instrumento (2.03 é
-- "Passivos Financeiros ao Custo Amortizado"), então o resto fica NULL. Seguradora:
-- circulante, caixa e PL batem com o padrão; 2.01.04/2.02.01 são provisões técnicas e
-- exigível a longo prazo, não dívida, e ficam NULL.
CREATE VIEW IF NOT EXISTS vw_balanco AS
SELECT
    f.cnpj_companhia,
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
JOIN demonstrativos_contabeis d
  ON  d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
  AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
WHERE f.tipo_doc IN ('BPA', 'BPP')
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

COMMIT;
