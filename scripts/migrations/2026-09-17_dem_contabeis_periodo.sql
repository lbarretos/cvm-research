.bail on
-- Reconstrói demonstrativos_contabeis com a chave natural nova (ver schema.sql).
-- SQLite não permite alterar uma UNIQUE inline: cria tabela nova, copia, troca.
-- Uso (na raiz do projeto, com backup feito antes):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-17_dem_contabeis_periodo.sql
--   sqlite3 cvm_research.db < schema.sql      # recria índices e views (IF NOT EXISTS)
-- As linhas existentes são preservadas; st_conta_fixa fica NULL até a reingestão.
--
-- IMPORTANTE — rode os dois comandos em sequência: entre este comando e o
-- `schema.sql` seguinte, vw_dre / vw_dre_acumulada / vw_balanco NÃO EXISTEM
-- (este script as derruba e não as recria). Qualquer query contra essas views
-- nessa janela falha; isso é esperado e temporário até rodar schema.sql.
--
-- ESCALA/PERFORMANCE — a tabela em produção tem ~4.45M linhas e o schema usa
-- PRAGMA journal_mode=WAL. Uma única transação copiando essa quantidade de
-- linhas pode gerar crescimento transitório significativo do WAL (espaço em
-- disco extra) antes do COMMIT, além de manter um lock de escrita longo.
-- Antes de rodar contra cvm_research.db em produção: confirme espaço livre em
-- disco (regra prática: pelo menos o tamanho atual em disco de
-- demonstrativos_contabeis novamente, para acomodar a cópia + WAL) e garanta
-- que não há leitores/escritores concorrentes acessando o banco durante a
-- migração.
--
-- .bail on (acima) é essencial: o cliente sqlite3 roda com `.bail off` por
-- padrão, o que faz com que uma falha no meio do script (disco cheio durante
-- o INSERT...SELECT de milhões de linhas, erro de I/O, etc.) seja apenas
-- reportada e a execução CONTINUE para as instruções seguintes — incluindo o
-- DROP TABLE e o COMMIT — destruindo a tabela original e commitando uma
-- substituição incompleta, apesar do BEGIN/COMMIT. Com `.bail on`, qualquer
-- falha aborta o script inteiro e a transação pendente é desfeita.

-- Precaução: nenhuma FK hoje referencia demonstrativos_contabeis, mas
-- desligamos o enforcement por segurança caso um schema futuro adicione uma
-- (evita falha de FK durante o DROP/CREATE/RENAME abaixo).
PRAGMA foreign_keys = OFF;
BEGIN;

-- Guarda de idempotência: st_conta_fixa só existe a partir desta migração.
-- Se a coluna já existir, o banco já foi migrado — rodar este arquivo de novo
-- recriaria demonstrativos_contabeis_new via um INSERT...SELECT que NUNCA
-- seleciona st_conta_fixa (porque, na versão pré-migração, essa coluna não
-- existia), zerando de volta para NULL qualquer valor 'S'/'N' já populado
-- pelos ingestores (Task 0.3). Abortamos alto e cedo em vez de silenciosamente
-- descartar esse dado.
CREATE TEMP TABLE _migration_guard (x INTEGER);
CREATE TEMP TRIGGER _migration_guard_check
BEFORE INSERT ON _migration_guard
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM pragma_table_info('demonstrativos_contabeis')
        WHERE name = 'st_conta_fixa'
    ) THEN
        RAISE(ABORT, 'Migração já aplicada: demonstrativos_contabeis.st_conta_fixa já existe. Rodar este script novamente apagaria os valores S/N já populados pelos ingestores. Abortando sem alterar nada.')
    END;
END;
INSERT INTO _migration_guard VALUES (1);
DROP TRIGGER _migration_guard_check;
DROP TABLE _migration_guard;

DROP VIEW IF EXISTS vw_dre;
DROP VIEW IF EXISTS vw_dre_acumulada;
DROP VIEW IF EXISTS vw_balanco;

CREATE TABLE demonstrativos_contabeis_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL DEFAULT 1,
    ordem_exercicio TEXT NOT NULL CHECK (ordem_exercicio IN ('Último', 'Penúltimo')),
    dt_ini_exerc    TEXT,
    dt_fim_exerc    TEXT,
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_conta        REAL,
    st_conta_fixa   TEXT CHECK (st_conta_fixa IN ('S', 'N')),
    created_at      TEXT DEFAULT (datetime('now'))
);

INSERT INTO demonstrativos_contabeis_new
    (id, cnpj_companhia, fonte, tipo_doc, data_referencia, versao, ordem_exercicio,
     dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta, created_at)
SELECT id, cnpj_companhia, fonte, tipo_doc, data_referencia, versao, ordem_exercicio,
       dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta, created_at
FROM demonstrativos_contabeis;

DROP TABLE demonstrativos_contabeis;
ALTER TABLE demonstrativos_contabeis_new RENAME TO demonstrativos_contabeis;

COMMIT;
