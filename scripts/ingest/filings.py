"""
Reconstrói a tabela `filings`: uma linha por (empresa, fonte, tipo_doc, data_referencia) com a
versão vigente (maior `versao` das linhas 'Último'), o plano de contas e o período da DRE.

As views vw_dre, vw_balanco e as demais leem dela em vez de recalcular MAX(versao) e o plano de
contas sobre a base inteira a cada consulta (Etapa 1 de docs/proximos-passos). Roda no fim de
ingest_dfp / ingest_itr e no início de run_all.py; ~4 s na base de 146 empresas.

    python scripts/ingest/filings.py        # reconstrói a partir do DATABASE_URL
"""
from utils import get_db

# Cópia literal em scripts/migrations/2026-10-05_filings_views.sql (tests/test_filings.py confere).
REBUILD_SQL = """
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
"""


def rebuild_filings(conn) -> int:
    """Reconstrói `filings` numa transação (leitores veem a tabela antiga ou a nova, nunca vazia)."""
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in REBUILD_SQL.split(";\n"):
            if stmt.strip():
                conn.execute(stmt)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]


def main():
    conn = get_db()
    print(f"filings: {rebuild_filings(conn)} linhas")


if __name__ == "__main__":
    main()
