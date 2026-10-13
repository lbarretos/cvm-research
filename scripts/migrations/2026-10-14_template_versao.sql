-- Etapa 5 (docs/proximos-passos/05-template-cvm.md): versão do template de contas da CVM.
-- Uso: sqlite3 cvm_research.db < scripts/migrations/2026-10-14_template_versao.sql
--      cd scripts/ingest && python template_versions.py       # preenche
-- Não é idempotente em ALTER TABLE: se filings já tem versao_template, ignore o erro da 1ª linha.
-- (template_versions.py também cria a coluna e as tabelas sozinho.)
ALTER TABLE filings ADD COLUMN versao_template TEXT;
CREATE TABLE IF NOT EXISTS plano_cvm (
    plano_contas TEXT NOT NULL, tipo_doc TEXT NOT NULL, versao_template TEXT NOT NULL,
    cd_conta TEXT NOT NULL, ds_conta_norm TEXT NOT NULL,
    PRIMARY KEY (plano_contas, tipo_doc, versao_template, cd_conta)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS plano_cvm_de_para (
    plano_contas TEXT NOT NULL, tipo_doc TEXT NOT NULL, versao_a TEXT NOT NULL, cd_a TEXT NOT NULL,
    versao_b TEXT NOT NULL, cd_b TEXT NOT NULL, ds_conta_norm TEXT NOT NULL,
    PRIMARY KEY (plano_contas, tipo_doc, versao_a, versao_b, cd_a)
) WITHOUT ROWID;
