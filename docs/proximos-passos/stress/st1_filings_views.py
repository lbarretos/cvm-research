"""Stress test da Etapa 1: tabela `filings` + views reescritas.

Roda sobre uma CÓPIA do banco (nunca sobre cvm_research.db): o banco de rascunho precisa ter
demonstrativos_contabeis, companies e as views atuais. Mede tempo por empresa (antes/depois)
e prova que as views novas devolvem exatamente as mesmas linhas das antigas.

    python st1_filings_views.py /caminho/copia.db
"""
import sqlite3
import statistics
import sys
import time

db = sys.argv[1]
c = sqlite3.connect(db)

DDL = """
DROP TABLE IF EXISTS filings;
CREATE TABLE filings (
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL,          -- maior versão com linhas 'Último'
    plano_contas    TEXT NOT NULL DEFAULT 'padrao',
    dt_ini_min      TEXT,                      -- início do acumulado (DRE)
    dt_ini_max      TEXT,                      -- início do trimestre isolado (DRE)
    n_linhas        INTEGER,
    PRIMARY KEY (cnpj_companhia, fonte, tipo_doc, data_referencia)
) WITHOUT ROWID;
INSERT INTO filings (cnpj_companhia, fonte, tipo_doc, data_referencia, versao)
SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao)
FROM demonstrativos_contabeis WHERE ordem_exercicio = 'Último'
GROUP BY 1, 2, 3, 4;
UPDATE filings SET
  (dt_ini_min, dt_ini_max, n_linhas) = (
    SELECT MIN(d.dt_ini_exerc), MAX(d.dt_ini_exerc), COUNT(*) FROM demonstrativos_contabeis d
    WHERE d.cnpj_companhia = filings.cnpj_companhia AND d.fonte = filings.fonte
      AND d.tipo_doc = filings.tipo_doc AND d.data_referencia = filings.data_referencia
      AND d.versao = filings.versao AND d.ordem_exercicio = 'Último');
-- plano do filing lido da DRE, replicado em todos os tipo_doc do mesmo (cnpj, fonte, data)
UPDATE filings SET plano_contas = COALESCE((
    SELECT CASE WHEN MAX(d.ds_conta LIKE '%Intermedia%Financeira%') THEN 'banco'
                WHEN MAX(d.ds_conta LIKE '%Segurador%' OR d.ds_conta = 'Receitas das Operações') THEN 'seguradora'
                ELSE 'padrao' END
    FROM filings f JOIN demonstrativos_contabeis d
      ON d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
     AND d.data_referencia = f.data_referencia AND d.versao = f.versao
    WHERE f.cnpj_companhia = filings.cnpj_companhia AND f.fonte = filings.fonte
      AND f.data_referencia = filings.data_referencia AND f.tipo_doc = 'DRE'
      AND d.ordem_exercicio = 'Último' AND d.cd_conta = '3.01'
    HAVING COUNT(*) > 0), 'padrao');

DROP VIEW IF EXISTS vw_plano_contas_v2;
CREATE VIEW vw_plano_contas_v2 AS
SELECT cnpj_companhia, fonte, data_referencia, plano_contas FROM filings WHERE tipo_doc = 'DRE';

DROP VIEW IF EXISTS vw_balanco_v2;
CREATE VIEW vw_balanco_v2 AS
SELECT f.cnpj_companhia, f.fonte, f.data_referencia,
    MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1'       THEN d.vl_conta END) AS ativo_total,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1.01'    AND f.plano_contas <> 'banco'  THEN d.vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN d.tipo_doc = 'BPA' AND d.cd_conta = '1.01.01' AND f.plano_contas <> 'banco'  THEN d.vl_conta END) AS caixa,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.01.04' AND f.plano_contas = 'padrao'  THEN d.vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.02.01' AND f.plano_contas = 'padrao'  THEN d.vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN d.tipo_doc = 'BPP' AND d.cd_conta = '2.03'    AND f.plano_contas <> 'banco'  THEN d.vl_conta END) AS patrimonio_liquido,
    MAX(f.plano_contas) AS plano_contas
FROM filings f
JOIN demonstrativos_contabeis d
  ON d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
 AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
WHERE f.tipo_doc IN ('BPA', 'BPP')
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;

DROP VIEW IF EXISTS vw_dre_v2;
CREATE VIEW vw_dre_v2 AS
SELECT f.cnpj_companhia, f.fonte, f.data_referencia,
    MIN(d.dt_ini_exerc) AS dt_ini_exerc, MIN(d.dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.01' THEN d.vl_conta END) AS receita_liquida,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.02' THEN d.vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.03' THEN d.vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.05' THEN d.vl_conta END) AS ebit,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.06' THEN d.vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.07' THEN d.vl_conta END) AS ebt,
    MAX(CASE WHEN f.plano_contas = 'padrao' AND d.cd_conta = '3.11' THEN d.vl_conta END) AS lucro_liquido,
    MAX(f.plano_contas) AS plano_contas
FROM filings f
JOIN demonstrativos_contabeis d
  ON d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
 AND d.data_referencia = f.data_referencia AND d.versao = f.versao AND d.ordem_exercicio = 'Último'
 AND COALESCE(d.dt_ini_exerc, '') = COALESCE(f.dt_ini_max, '')
WHERE f.tipo_doc = 'DRE'
GROUP BY f.cnpj_companhia, f.fonte, f.data_referencia;
"""

t = time.time()
c.executescript(DDL)
c.commit()
print(f"build filings: {time.time() - t:.1f}s, {c.execute('select count(*) from filings').fetchone()[0]} linhas")

# 1) Equivalência: as views novas devolvem exatamente as linhas das antigas (base inteira)
for old, new in [("vw_plano_contas", "vw_plano_contas_v2"), ("vw_balanco", "vw_balanco_v2"), ("vw_dre", "vw_dre_v2")]:
    t = time.time()
    a = c.execute(f"SELECT COUNT(*) FROM (SELECT * FROM {old} EXCEPT SELECT * FROM {new})").fetchone()[0]
    b = c.execute(f"SELECT COUNT(*) FROM (SELECT * FROM {new} EXCEPT SELECT * FROM {old})").fetchone()[0]
    n = c.execute(f"SELECT COUNT(*) FROM {old}").fetchone()[0]
    print(f"equivalência {old}: {n} linhas; só na antiga={a}, só na nova={b} ({time.time() - t:.0f}s)")

# 2) Latência por empresa: consulta típica da skill
cnpjs = [r[0] for r in c.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
Q = {
    "balanco": "SELECT * FROM {v} WHERE cnpj_companhia = ? AND fonte = 'DFP' ORDER BY data_referencia DESC LIMIT 5",
    "dre": "SELECT * FROM {v} WHERE cnpj_companhia = ? AND fonte = 'ITR' ORDER BY data_referencia DESC LIMIT 8",
}
amostra_antiga = cnpjs[:: max(1, len(cnpjs) // 8)]
for nome, sql in Q.items():
    for v, alvo in [(f"vw_{nome}", amostra_antiga), (f"vw_{nome}_v2", cnpjs)]:
        ts = []
        for cn in alvo:
            t = time.time()
            c.execute(sql.format(v=v), (cn,)).fetchall()
            ts.append(time.time() - t)
        ts.sort()
        print(f"{v:18s} n={len(ts):3d}  p50={statistics.median(ts)*1000:9.1f} ms  p95={ts[int(.95*(len(ts)-1))]*1000:9.1f} ms  max={ts[-1]*1000:9.1f} ms")

# 3) Carga: todas as empresas, uma após a outra (o que um screen faria)
t = time.time()
c.execute("SELECT * FROM vw_dre_v2 WHERE fonte='DFP' AND data_referencia='2024-12-31'").fetchall()
print(f"screen DFP 2024 (todas as empresas) vw_dre_v2: {(time.time()-t)*1000:.0f} ms")
t = time.time()
c.execute("SELECT * FROM vw_dre WHERE fonte='DFP' AND data_referencia='2024-12-31'").fetchall()
print(f"screen DFP 2024 (todas as empresas) vw_dre   : {(time.time()-t)*1000:.0f} ms")
