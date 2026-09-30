.bail on
-- Lucro por ação (DRE 3.99 e descendentes) volta para R$/ação.
-- ingest_dfp.py / ingest_itr.py multiplicavam VL_CONTA por 1000 em todo filing com
-- ESCALA_MOEDA = 'MIL', inclusive no LPA, que a CVM publica em R$/ação qualquer
-- que seja a escala: Petrobras DFP 2025 3.99.01.01 estava 8.540 (é 8,54).
-- O código novo (utils.vl_escalado) não escala 3.99; aqui corrigimos o que já está no banco.
--
-- Só divide filings MIL. O banco não guarda ESCALA_MOEDA, então os filings UNIDADE
-- estão listados abaixo: é o que os ZIPs de DFP (2010–2026) e ITR (2011–2026)
-- traziam em 30/09/2026 para todo CNPJ com linhas em demonstrativos_contabeis
-- (7.143 filings MIL, 31 UNIDADE; os 31 já têm LPA correto, ex. VAMO3 DFP 2018 = 0,34).
-- Um filing UNIDADE que entre depois desta data já entra certo pelo código novo.
--
-- Uso (na raiz do projeto, com backup feito antes e o código novo já em main —
-- o update_weekly.sh com o ingestor antigo reescreveria os anos recentes ×1000):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-30_lpa_escala.sql
--   cd scripts/analysis && ../../.venv/bin/python run_all.py --layer 1,2,3,5,6 --full
-- As Camadas 2 e 3 comparam 3.99 com a tolerância max(R$ 1.000, 1%): os flags delas
-- mudam com a escala. Camadas 1 e 6 ignoram 3.99.
--
-- NÃO é idempotente (dividir duas vezes estraga o dado): a linha em
-- schema_migrations impede a segunda execução. Banco montado do zero com o código
-- novo não precisa desta migração: não rode nele.

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    nome        TEXT PRIMARY KEY,
    aplicada_em TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Falha com UNIQUE constraint se já aplicada; .bail on aborta antes do UPDATE.
INSERT INTO schema_migrations (nome) VALUES ('2026-09-30_lpa_escala');

CREATE TEMP TABLE _filings_unidade (cnpj_companhia TEXT, fonte TEXT, data_referencia TEXT, versao INTEGER);
INSERT INTO _filings_unidade VALUES
    ('23.373.000/0001-32', 'DFP', '2018-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2019-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2020-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2021-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2022-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2023-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2024-12-31', 1),
    ('33.839.910/0001-11', 'DFP', '2025-12-31', 1),
    ('33.839.910/0001-11', 'ITR', '2019-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2019-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2020-03-31', 1),
    ('33.839.910/0001-11', 'ITR', '2020-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2020-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2021-03-31', 1),
    ('33.839.910/0001-11', 'ITR', '2021-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2021-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2022-03-31', 1),
    ('33.839.910/0001-11', 'ITR', '2022-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2022-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2023-03-31', 2),
    ('33.839.910/0001-11', 'ITR', '2023-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2023-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2024-03-31', 1),
    ('33.839.910/0001-11', 'ITR', '2024-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2024-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2025-03-31', 1),
    ('33.839.910/0001-11', 'ITR', '2025-06-30', 1),
    ('33.839.910/0001-11', 'ITR', '2025-09-30', 1),
    ('33.839.910/0001-11', 'ITR', '2026-03-31', 1),
    ('33.839.910/0001-11', 'ITR', '2026-06-30', 1),
    ('58.119.199/0001-51', 'ITR', '2021-06-30', 1);

UPDATE demonstrativos_contabeis
SET vl_conta = vl_conta / 1000.0
WHERE tipo_doc = 'DRE'
  AND cd_conta LIKE '3.99%'
  AND vl_conta IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM _filings_unidade u
      WHERE u.cnpj_companhia  = demonstrativos_contabeis.cnpj_companhia
        AND u.fonte           = demonstrativos_contabeis.fonte
        AND u.data_referencia = demonstrativos_contabeis.data_referencia
        AND u.versao          = demonstrativos_contabeis.versao
  );

DROP TABLE _filings_unidade;

COMMIT;
