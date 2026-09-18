# Consistência de Dados Financeiros (DRE/Balanço/DFC) Implementation Plan

> **Revisão 2026-09-17.** Substitui o plano de 2026-09-16 (`~/.claude/plans/quero-uma-revis-o-mais-cheeky-reddy.md`, agora só um ponteiro para este arquivo). A revisão independente rodou as premissas do plano original contra o `cvm_research.db` e mudou o desenho em seis pontos, listados em "O que mudou em relação ao plano original". Todos os números citados aqui vieram de queries reais nesta base.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **A Fase 0 está em nível de tarefa (código completo). As Fases 1–5 estão em nível de desenho e devem ser expandidas em plano de tarefas próprio quando forem iniciadas**, seguindo o precedente deste arquivo.

**Goal:** Deixar `demonstrativos_contabeis` completa e sem corrupção de período, e adicionar uma camada de metadados que diga, linha a linha, o que é confiável, o que foi reapresentado, o que mudou de código ou de nome, e qual é o valor trimestral derivado.

**Architecture:** Primeiro corrige-se o ingestor (a chave única não inclui `dt_ini_exerc`, então o ITR de 2T/3T perde o acumulado e mistura períodos; e duas colunas da CVM, `DT_INI_EXERC` do DFP e `ST_CONTA_FIXA`, são descartadas). Só depois entram as camadas de verificação, gravadas em tabelas próprias (`consistency_runs`, `consistency_flags`, `cd_conta_ds_timeline`, `demonstrativos_trimestrais`), nunca alterando o valor publicado pela CVM. Scripts standalone em `scripts/analysis/`, fora do job semanal.

**Tech Stack:** Python 3, `pandas`, `sqlite3` (≥ 3.24 para UPSERT com índice de expressão — o Python do `.venv` tem 3.50), `difflib` (stdlib), `pytest`.

---

## O que mudou em relação ao plano original

| # | Plano original dizia | O que a base mostra | Consequência no desenho |
|---|---|---|---|
| 1 | `dt_ini_exerc` sempre preenchido em DRE/DFC/DVA do ITR; chave de período pronta | Verdadeiro, mas a `UNIQUE` não tem `dt_ini_exerc`. No 2T/3T a CVM publica cada conta da DRE duas vezes (trimestre e acumulado) e o upsert guarda uma por acaso: 98% dos docs misturados, 585 linhas acumuladas com valor real dentro de docs trimestrais (ex: PETR4 3T14 conta 3.04.05.06, −R$ 6,2 bi). O acumulado foi descartado. | **Fase 0 nova**, antes de qualquer camada: chave com `dt_ini_exerc`, reingestão. |
| 2 | "DFP não publica DT_INI_EXERC"; nível 3+ é numeração livre por empresa | O CSV do DFP tem `DT_INI_EXERC` em DRE/DFC/DVA. E DFP e ITR têm `ST_CONTA_FIXA` (S/N): na DRE 2024, nível 3 é 81% padrão (13.078 S contra 2.982 N). | Gravar `st_conta_fixa` e usar em vez de heurística por nível. |
| 3 | WEGE3 BPA DFP × ITR bate com diff=0; Camada 2 é "resultado exato" | 38% dos pares empresa-ano têm divergência (BPA 38,3%, DRE anual 37,9%, DRE trimestral 35,3%). Receita reapresentada em 196 pares, lucro em 113. Em 15% dos docs há códigos sem par (renumeração). | Camada 2 ganha baseline (filing mais antigo), classificação `reapresentacao` / `reclassificacao` / `erro` e casamento por nome para códigos sem par. |
| 4 | Camada 1A flaga `\|pai − Σ filhos\| > tol` | Somas batem em 93–99%, mas **todas** as 847 falhas de BPA/BPP são "pai preenchido, filhos zerados". Divergência real em 2023+2024: BPA 0, BPP 0, DRE 8, DVA 3. Exceções estruturais: `6.05` (filhos são saldo inicial/final; `6.05 = 6.05.02 − 6.05.01` em 99,8%) e `3.99.xx` (lucro por ação, 46%). | Categoria `nao_detalhado` (info) e tabela de exceções. Camada 1 vira teste de regressão de ingestão. |
| 5 | Camada 1B calibra sinais empiricamente (`calibrate_signals.py`) | Cadeia de nível 2 da DRE bate em 99,8–100% dos DFPs não financeiros sem calibração, todos os sinais +1. | **Camada 1B removida.** Tabela fixa de 6 fórmulas. |
| 6 | Camada 5 chaveada em `(cnpj, tipo_doc, cd_conta)`, limiar único 0,6 | Em 28% das mudanças de `ds_conta` na DFC_MI o texto antigo reaparece em outro código do mesmo filing (renumeração). `difflib` é bimodal com 13% na zona 0,5–0,7; 0,52 era reclassificação real e 0,56 era reformulação. | Chave em `(cnpj, tipo_doc, pai, ds_conta normalizado)`, classe `renumerado`, dois limiares (≥ 0,75 / ≤ 0,45) com `ambiguo` no meio. |

Achados do plano original que **continuam válidos**: hierarquia de `cd_conta` padronizada até nível 2 para não financeiros; setor `Financeiro` (COSIF) diverge do nível 2 em diante e fica fora das fórmulas; instabilidade textual maior em DFC_MI; tolerância com piso de R$ 1.000 (na DRE ela sobe o acerto de 81% para 87,6%; nos demais tipos quase não muda).

## Decisões de produto (fechadas com o usuário em 2026-09-17)

1. **Valor padrão é o original**, como reportado na época (`ordem_exercicio = 'Último'` do próprio filing). É a única série completa e é o que o mercado viu. O reapresentado fica disponível ao lado, nunca no lugar.
2. **Nunca subtrair valores de safras diferentes.** Todo trimestre derivado sai de dois números da mesma safra (ambos originais ou ambos reapresentados).
3. **Trimestre da DRE vem da linha trimestral publicada** no ITR (`dt_ini_exerc` = início do trimestre). DFC e DVA só têm acumulado no ITR e são sempre derivados. 4T é sempre derivado (`DFP − acumulado 3T`).
4. **Derivado nunca sobrescreve publicado.** Vai para tabela própria com `origem`, `safra` e `flag`.

## Fases

| Fase | Entrega | Pré-requisito | Nível deste documento |
|---|---|---|---|
| 0 | Ingestor: chave com `dt_ini_exerc`, `st_conta_fixa`, `DT_INI_EXERC` do DFP, migração, reingestão, `vw_dre` por período | — | **Tarefas com código** |
| 1 | `consistency_runs` + `consistency_flags` + Camada 2 (cruzamento entre filings) com baseline e classificação | Fase 0 | Desenho |
| 2 | Camada 1 (soma hierárquica) com `nao_detalhado`, exceções e fórmulas fixas de nível 2 | Fase 1 (tabelas) | Desenho |
| 3 | Camada 3 (granularidade) com casamento por nome antes de "Outros" | Fase 1 | Desenho |
| 4 | Camada 5 (`cd_conta_ds_timeline` por pai + nome) + Camada 4 (similaridade, dois limiares) | Fase 0 (`st_conta_fixa`) | Desenho |
| 5 | Camada 6 (desacúmulo) + `demonstrativos_trimestrais` | Fase 0 | Desenho |
| 6 (futuro) | Agrupamento semântico entre empresas em linhas `st_conta_fixa = 'N'` | Fase 4 | Fora de escopo |

---

## Fase 0 — Ingestor e schema

### File Structure

- **Modify:** `schema.sql` — `demonstrativos_contabeis` ganha `st_conta_fixa`, perde a `UNIQUE` inline e ganha índice único de expressão; `vw_dre` passa a escolher período; nova `vw_dre_acumulada`; `vw_balanco` resolve versão por documento.
- **Create:** `scripts/migrations/2026-09-17_dem_contabeis_periodo.sql` — reconstrói a tabela no banco existente (SQLite não altera `UNIQUE` inline).
- **Modify:** `scripts/ingest/utils.py` — chave de conflito com expressão (`_INDEX_COLUMNS`) e colunas de dedup separadas (`_DEDUP_COLUMNS`).
- **Modify:** `scripts/ingest/ingest_dfp.py`, `scripts/ingest/ingest_itr.py` — gravam `dt_ini_exerc` (DFP) e `st_conta_fixa`; `KEY_COLS` com `DT_INI_EXERC`; `CONFLICT = "dem_contabeis_uniq"`.
- **Create:** `tests/test_ingest_periodo.py` — `process_df` com linhas trimestre+acumulado, upsert com índice de expressão.
- **Modify:** `CLAUDE.md` (seção `demonstrativos_contabeis` e query "DRE trimestral"), `README.md` (tabela de fontes), `scripts/mcp/cvm_mcp.py` (docstring de `query`).

### Task 0.1: Schema — tabela, índice único de expressão e views por período

**Files:**
- Modify: `schema.sql:248-268` (tabela e índices), `schema.sql:311-378` (views)

- [ ] **Step 1: Substituir a definição da tabela em `schema.sql`**

Trocar o bloco `CREATE TABLE IF NOT EXISTS demonstrativos_contabeis (...)` e seus quatro índices por:

```sql
-- Chave natural inclui o período (dt_ini_exerc): no ITR de 2T/3T a CVM publica
-- cada conta da DRE duas vezes (trimestre isolado e acumulado no ano). Sem
-- dt_ini_exerc na chave, o upsert guardava uma das duas por acaso.
-- A UNIQUE é um índice de expressão porque dt_ini_exerc é NULL em BPA/BPP e
-- NULLs são distintos entre si numa UNIQUE comum (o upsert nunca conflitaria).
CREATE TABLE IF NOT EXISTS demonstrativos_contabeis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL DEFAULT 1,
    ordem_exercicio TEXT NOT NULL CHECK (ordem_exercicio IN ('Último', 'Penúltimo')),
    dt_ini_exerc    TEXT,                 -- NULL em BPA/BPP (posição, não fluxo)
    dt_fim_exerc    TEXT,
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_conta        REAL,
    st_conta_fixa   TEXT CHECK (st_conta_fixa IN ('S', 'N')),  -- S = conta padrão CVM, N = criada pela empresa; NULL = linha anterior à migração 2026-09-17
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dem_periodo ON demonstrativos_contabeis
    (cnpj_companhia, fonte, tipo_doc, data_referencia, versao, cd_conta, ordem_exercicio, COALESCE(dt_ini_exerc, ''));

CREATE INDEX IF NOT EXISTS idx_dem_cnpj_fonte ON demonstrativos_contabeis (cnpj_companhia, fonte, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_dem_tipo_conta ON demonstrativos_contabeis (tipo_doc, cd_conta);
CREATE INDEX IF NOT EXISTS idx_dem_cnpj_tipo  ON demonstrativos_contabeis (cnpj_companhia, tipo_doc, data_referencia DESC);
```

O índice `idx_dem_versao` antigo sai: `ux_dem_periodo` cobre o mesmo prefixo.

- [ ] **Step 2: Substituir `vw_dre` e adicionar `vw_dre_acumulada`**

```sql
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
    MAX(CASE WHEN cd_conta = '3.08' THEN vl_conta END) AS ebt,
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
    MAX(CASE WHEN cd_conta = '3.08' THEN vl_conta END) AS ebt,
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;
```

- [ ] **Step 3: Em `vw_balanco`, resolver versão por documento**

Trocar a CTE `versao_max` de `vw_balanco` por:

```sql
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc IN ('BPA', 'BPP') AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia
),
```

e remover `AND d.cd_conta = v.cd_conta` do JOIN de `latest`. O resto da view fica igual.

- [ ] **Step 4: Validar o schema num banco vazio**

Run: `sqlite3 /tmp/schema_check.db < schema.sql && sqlite3 /tmp/schema_check.db ".indexes demonstrativos_contabeis" && rm /tmp/schema_check.db`
Expected: lista contendo `ux_dem_periodo`, `idx_dem_cnpj_fonte`, `idx_dem_tipo_conta`, `idx_dem_cnpj_tipo`, sem erro.

- [ ] **Step 5: Commit**

```bash
git add schema.sql
git commit -m "feat(schema): chave de demonstrativos_contabeis inclui periodo; st_conta_fixa; vw_dre por periodo"
```

### Task 0.2: Migração do banco existente

**Files:**
- Create: `scripts/migrations/2026-09-17_dem_contabeis_periodo.sql`

- [ ] **Step 1: Escrever a migração**

```sql
-- Reconstrói demonstrativos_contabeis com a chave natural nova (ver schema.sql).
-- SQLite não permite alterar uma UNIQUE inline: cria tabela nova, copia, troca.
-- Uso (na raiz do projeto, com backup feito antes):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-17_dem_contabeis_periodo.sql
--   sqlite3 cvm_research.db < schema.sql      # recria índices e views (IF NOT EXISTS)
-- As linhas existentes são preservadas; st_conta_fixa fica NULL até a reingestão.
PRAGMA foreign_keys = OFF;
BEGIN;

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
```

- [ ] **Step 2: Testar a migração numa cópia pequena**

```bash
sqlite3 /tmp/mig_test.db < schema.sql
sqlite3 /tmp/mig_test.db "INSERT INTO demonstrativos_contabeis (cnpj_companhia,fonte,tipo_doc,data_referencia,versao,ordem_exercicio,dt_ini_exerc,dt_fim_exerc,cd_conta,ds_conta,vl_conta) VALUES ('x','ITR','DRE','2024-06-30',1,'Último','2024-04-01','2024-06-30','3.01','Receita',1);"
sqlite3 /tmp/mig_test.db < scripts/migrations/2026-09-17_dem_contabeis_periodo.sql
sqlite3 /tmp/mig_test.db < schema.sql
sqlite3 /tmp/mig_test.db "SELECT COUNT(*) FROM demonstrativos_contabeis; SELECT name FROM sqlite_master WHERE name IN ('ux_dem_periodo','vw_dre','vw_dre_acumulada','vw_balanco');"
rm /tmp/mig_test.db
```

Expected: `1` e os quatro nomes.

- [ ] **Step 3: Commit**

```bash
git add scripts/migrations/2026-09-17_dem_contabeis_periodo.sql
git commit -m "feat(migration): reconstroi demonstrativos_contabeis com chave por periodo"
```

### Task 0.3: `utils.py` — conflito com expressão e dedup por coluna

**Files:**
- Modify: `scripts/ingest/utils.py:46-54` e `:138-147`
- Test: `tests/test_ingest_periodo.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""
Fase 0 da consistência financeira: chave natural com período.

Cobre:
  - _upsert_sqlite com índice único de expressão (COALESCE(dt_ini_exerc,''))
  - process_df (ITR e DFP) preserva trimestre + acumulado e grava st_conta_fixa
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _upsert_sqlite
import ingest_itr
import ingest_dfp

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _row(dt_ini, vl, cd="3.01"):
    return {
        "cnpj_companhia": "84.429.695/0001-11", "fonte": "ITR", "tipo_doc": "DRE",
        "data_referencia": "2024-06-30", "versao": 1, "ordem_exercicio": "Último",
        "dt_ini_exerc": dt_ini, "dt_fim_exerc": "2024-06-30",
        "cd_conta": cd, "ds_conta": "Receita", "vl_conta": vl, "st_conta_fixa": "S",
    }


def test_upsert_mantem_trimestre_e_acumulado():
    conn = _db()
    rows = [_row("2024-01-01", 17_307_730_000.0), _row("2024-04-01", 9_274_426_000.0)]
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, "dem_contabeis_uniq")
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, "dem_contabeis_uniq")  # idempotente
    got = conn.execute(
        "SELECT dt_ini_exerc, vl_conta FROM demonstrativos_contabeis ORDER BY dt_ini_exerc"
    ).fetchall()
    assert got == [("2024-01-01", 17_307_730_000.0), ("2024-04-01", 9_274_426_000.0)]


def test_upsert_dt_ini_null_conflita_consigo_mesmo():
    """BPA/BPP têm dt_ini_exerc NULL; duas cargas não podem duplicar a linha."""
    conn = _db()
    r = _row(None, 1.0, cd="1")
    r.update({"tipo_doc": "BPA", "vl_conta": 1.0})
    _upsert_sqlite(conn, "demonstrativos_contabeis", [r], "dem_contabeis_uniq")
    r["vl_conta"] = 2.0
    _upsert_sqlite(conn, "demonstrativos_contabeis", [r], "dem_contabeis_uniq")
    got = conn.execute("SELECT COUNT(*), MAX(vl_conta) FROM demonstrativos_contabeis").fetchone()
    assert got == (1, 2.0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_ingest_periodo.py -v`
Expected: FAIL — `sqlite3.OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint` (o conflito `dem_contabeis_uniq` ainda não está mapeado) ou erro de coluna `st_conta_fixa` se o schema da Task 0.1 não tiver sido aplicado.

- [ ] **Step 3: Implementar em `utils.py`**

Substituir o bloco `_INDEX_COLUMNS` por:

```python
_INDEX_COLUMNS: dict[str, str] = {
    # nome_index -> alvo do ON CONFLICT (col1,col2,... ou expressões do índice único)
    "vlmo_mov_uniq": (
        "cnpj_companhia,data_referencia,versao,empresa,"
        "tipo_cargo,tipo_movimentacao,tipo_ativo,caracteristica,"
        "data_movimentacao,quantidade"
    ),
    # ux_dem_periodo em schema.sql — índice de expressão porque dt_ini_exerc é
    # NULL em BPA/BPP e NULLs não conflitam entre si numa UNIQUE comum.
    "dem_contabeis_uniq": (
        "cnpj_companhia,fonte,tipo_doc,data_referencia,versao,cd_conta,ordem_exercicio,"
        "COALESCE(dt_ini_exerc,'')"
    ),
}

# Quando o alvo do conflito tem expressões, a deduplicação em Python precisa
# das colunas puras (None == None já trata o NULL como igual).
_DEDUP_COLUMNS: dict[str, str] = {
    "dem_contabeis_uniq": (
        "cnpj_companhia,fonte,tipo_doc,data_referencia,versao,cd_conta,ordem_exercicio,dt_ini_exerc"
    ),
}
```

E em `_upsert_sqlite`, trocar:

```python
    conflict_cols = _INDEX_COLUMNS.get(conflict, conflict)
    conflict_list = [c.strip() for c in conflict_cols.split(",")]
```

por:

```python
    conflict_cols = _INDEX_COLUMNS.get(conflict, conflict)
    dedup_cols = _DEDUP_COLUMNS.get(conflict, conflict_cols)
    conflict_list = [c.strip() for c in dedup_cols.split(",")]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_ingest_periodo.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest/utils.py tests/test_ingest_periodo.py
git commit -m "feat(utils): upsert de demonstrativos_contabeis usa chave com periodo (indice de expressao)"
```

### Task 0.4: `ingest_itr.py` e `ingest_dfp.py` — período e `st_conta_fixa`

**Files:**
- Modify: `scripts/ingest/ingest_itr.py:25-70`, `scripts/ingest/ingest_dfp.py:22-75`
- Test: `tests/test_ingest_periodo.py`

- [ ] **Step 1: Adicionar os testes que falham**

Acrescentar ao final de `tests/test_ingest_periodo.py`:

```python
def _csv_rows_itr_2t24():
    """As 4 linhas reais de 3.01 da WEG no ITR 2T24 (itr_cia_aberta_DRE_con_2024.csv)."""
    base = {"CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-06-30", "VERSAO": "1",
            "ESCALA_MOEDA": "MIL", "CD_CONTA": "3.01",
            "DS_CONTA": "Receita de Venda de Bens e/ou Serviços", "ST_CONTA_FIXA": "S"}
    return pd.DataFrame([
        {**base, "ORDEM_EXERC": "PENÚLTIMO", "DT_INI_EXERC": "2023-01-01", "DT_FIM_EXERC": "2023-06-30", "VL_CONTA": "15867479.0000000000"},
        {**base, "ORDEM_EXERC": "PENÚLTIMO", "DT_INI_EXERC": "2023-04-01", "DT_FIM_EXERC": "2023-06-30", "VL_CONTA": "8171322.0000000000"},
        {**base, "ORDEM_EXERC": "ÚLTIMO",    "DT_INI_EXERC": "2024-01-01", "DT_FIM_EXERC": "2024-06-30", "VL_CONTA": "17307730.0000000000"},
        {**base, "ORDEM_EXERC": "ÚLTIMO",    "DT_INI_EXERC": "2024-04-01", "DT_FIM_EXERC": "2024-06-30", "VL_CONTA": "9274426.0000000000"},
    ])


def test_itr_process_df_preserva_trimestre_e_acumulado():
    rows = ingest_itr.process_df(_csv_rows_itr_2t24(), {"84.429.695/0001-11"}, "DRE")
    assert len(rows) == 4
    ultimo = sorted((r["dt_ini_exerc"], r["vl_conta"]) for r in rows if r["ordem_exercicio"] == "Último")
    assert ultimo == [("2024-01-01", 17_307_730_000.0), ("2024-04-01", 9_274_426_000.0)]
    assert {r["st_conta_fixa"] for r in rows} == {"S"}


def test_itr_upsert_ponta_a_ponta_nao_mistura_periodos():
    conn = _db()
    rows = ingest_itr.process_df(_csv_rows_itr_2t24(), {"84.429.695/0001-11"}, "DRE")
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, ingest_itr.CONFLICT)
    n = conn.execute("SELECT COUNT(*) FROM demonstrativos_contabeis").fetchone()[0]
    assert n == 4
    tri = conn.execute("SELECT receita_liquida FROM vw_dre").fetchone()[0]
    acu = conn.execute("SELECT receita_liquida FROM vw_dre_acumulada").fetchone()[0]
    assert (tri, acu) == (9_274_426_000.0, 17_307_730_000.0)


def test_dfp_process_df_grava_dt_ini_e_st_conta_fixa():
    df = pd.DataFrame([{
        "CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-12-31", "VERSAO": "1",
        "ESCALA_MOEDA": "MIL", "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": "2024-01-01", "DT_FIM_EXERC": "2024-12-31",
        "CD_CONTA": "3.04.01.02", "DS_CONTA": "Outras Despesas de Vendas",
        "VL_CONTA": "-2500000.0", "ST_CONTA_FIXA": "N",
    }])
    rows = ingest_dfp.process_df(df, {"84.429.695/0001-11"}, "DRE")
    assert rows[0]["dt_ini_exerc"] == "2024-01-01"
    assert rows[0]["st_conta_fixa"] == "N"


def test_dfp_bpa_sem_dt_ini_fica_none():
    df = pd.DataFrame([{
        "CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-12-31", "VERSAO": "1",
        "ESCALA_MOEDA": "MIL", "ORDEM_EXERC": "ÚLTIMO",
        "DT_FIM_EXERC": "2024-12-31", "CD_CONTA": "1", "DS_CONTA": "Ativo Total",
        "VL_CONTA": "1.0", "ST_CONTA_FIXA": "S",
    }])
    rows = ingest_dfp.process_df(df, {"84.429.695/0001-11"}, "BPA")
    assert rows[0]["dt_ini_exerc"] is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_ingest_periodo.py -v`
Expected: os 4 testes novos falham com `KeyError: 'st_conta_fixa'` (o dict de saída ainda não tem a chave). Nota: `drop_duplicates` sem `DT_INI_EXERC` não derruba a contagem neste fixture porque os 4 valores são distintos; a correção do `KEY_COLS` protege o caso em que trimestre e acumulado têm o mesmo valor (linhas zeradas, 98% dos casos reais).

- [ ] **Step 3: Alterar `ingest_itr.py`**

```python
CONFLICT = "dem_contabeis_uniq"   # ver utils._INDEX_COLUMNS — chave inclui o período
```

Em `process_df`, trocar `KEY_COLS` e o dict de saída:

```python
    # A chave natural inclui o período: no 2T/3T a CVM publica cada conta da
    # DRE duas vezes (trimestre isolado e acumulado no ano) e as duas são dados.
    KEY_COLS = ["CNPJ_CIA", "DT_REFER", "VERSAO", "CD_CONTA", "ORDEM_EXERC", "DT_INI_EXERC"]
    df = df.drop_duplicates(subset=KEY_COLS + ["VL_CONTA"])
```

```python
        st_fixa = (r.get("ST_CONTA_FIXA") or "").strip().upper()

        rows.append({
            "cnpj_companhia":  r.get("CNPJ_CIA"),
            "fonte":           FONTE,
            "tipo_doc":        tipo_doc,
            "data_referencia": _date(r.get("DT_REFER")),
            "versao":          versao,
            "ordem_exercicio": ORDEM_MAP.get(ordem_raw, ordem_raw),
            "dt_ini_exerc":    _date(r.get("DT_INI_EXERC")),
            "dt_fim_exerc":    _date(r.get("DT_FIM_EXERC")),
            "cd_conta":        r.get("CD_CONTA"),
            "ds_conta":        r.get("DS_CONTA"),
            "vl_conta":        vl,
            "st_conta_fixa":   st_fixa if st_fixa in ("S", "N") else None,
        })
```

Atualizar o docstring do módulo: remover "Cobertura: 2021-atual" (a base tem ITR desde 2011) e acrescentar a frase "Grava trimestre isolado e acumulado como linhas distintas (`dt_ini_exerc`)".

- [ ] **Step 4: Alterar `ingest_dfp.py`**

Mesmas três mudanças (`CONFLICT`, `KEY_COLS`, dict de saída). No dict, `"dt_ini_exerc": _date(r.get("DT_INI_EXERC"))` — o CSV de BPA/BPP não tem a coluna, `r.get` devolve `None` e `_date(None)` devolve `None`. Apagar a nota "DFP não tem DT_INI_EXERC" do docstring (é falsa: DRE/DFC/DVA do DFP trazem `DT_INI_EXERC`) e substituir por "BPA/BPP não têm DT_INI_EXERC (posição na data); DRE/DFC/DVA têm".

- [ ] **Step 5: Rodar todos os testes**

Run: `.venv/bin/pytest tests/ -v`
Expected: todos passam, incluindo os 6 de `test_ingest_periodo.py`.

- [ ] **Step 6: Commit**

```bash
git add scripts/ingest/ingest_itr.py scripts/ingest/ingest_dfp.py tests/test_ingest_periodo.py
git commit -m "feat(ingest): DFP/ITR gravam dt_ini_exerc e st_conta_fixa; ITR preserva trimestre e acumulado"
```

### Task 0.5: Migrar e reingerir o banco real

**Files:** nenhum novo. Toca `cvm_research.db` (12 GB). 193 GB livres no disco em 2026-09-17.

- [ ] **Step 1: Backup**

```bash
cp cvm_research.db cvm_research.db.bak-2026-09-17
```

- [ ] **Step 2: Migrar**

```bash
sqlite3 cvm_research.db < scripts/migrations/2026-09-17_dem_contabeis_periodo.sql
sqlite3 cvm_research.db < schema.sql
sqlite3 cvm_research.db "SELECT COUNT(*) FROM demonstrativos_contabeis; SELECT name FROM sqlite_master WHERE name='ux_dem_periodo';"
```

Expected: `4451524` (mesma contagem de antes) e `ux_dem_periodo`.

- [ ] **Step 3: Reingerir DFP e ITR completos** (16 + 16 ZIPs de 13–200 MB; estimar 30–60 min)

```bash
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_dfp.py --historico --desde 2010
python ingest_itr.py --desde 2011
cd ../..
```

- [ ] **Step 4: Verificar o resultado**

```bash
sqlite3 -header -column cvm_research.db "
-- (a) nenhuma linha sem st_conta_fixa
SELECT SUM(st_conta_fixa IS NULL) AS sem_flag, COUNT(*) AS total FROM demonstrativos_contabeis;
-- (b) DFP DRE com dt_ini preenchido
SELECT SUM(dt_ini_exerc IS NULL) AS dfp_dre_sem_ini FROM demonstrativos_contabeis WHERE fonte='DFP' AND tipo_doc='DRE';
-- (c) todo doc ITR DRE de 2T/3T tem exatamente 2 dt_ini distintos por conta (trimestre + acumulado)
SELECT COUNT(*) AS contas_com_1_periodo FROM (
  SELECT cnpj_companhia, data_referencia, versao, ordem_exercicio, cd_conta, COUNT(DISTINCT dt_ini_exerc) n
  FROM demonstrativos_contabeis
  WHERE fonte='ITR' AND tipo_doc='DRE' AND substr(data_referencia,6,2) IN ('06','09')
  GROUP BY 1,2,3,4,5 HAVING n <> 2);
-- (d) WEG 2T24: trimestre 9.274 mi, acumulado 17.308 mi
SELECT 'tri' k, receita_liquida/1e6 FROM vw_dre WHERE cnpj_companhia='84.429.695/0001-11' AND fonte='ITR' AND data_referencia='2024-06-30'
UNION ALL
SELECT 'acu', receita_liquida/1e6 FROM vw_dre_acumulada WHERE cnpj_companhia='84.429.695/0001-11' AND fonte='ITR' AND data_referencia='2024-06-30';
"
```

Expected: (a) `sem_flag = 0`; (b) `0`; (c) um número pequeno, explicável só por anos antigos onde a CVM publicou uma linha (conferir os casos com `SELECT DISTINCT data_referencia` — se aparecerem anos recentes, o `KEY_COLS` está errado); (d) `9274.426` e `17307.73`.

- [ ] **Step 5: Compactar e remover o backup só depois de (a)–(d) passarem**

```bash
sqlite3 cvm_research.db "VACUUM;"
rm cvm_research.db.bak-2026-09-17
```

### Task 0.6: Documentação

**Files:**
- Modify: `CLAUDE.md:70-79` e a query "DRE trimestral (últimos 8 trimestres) via view" (`CLAUDE.md:208-216`)
- Modify: `README.md:160-161`
- Modify: `scripts/mcp/cvm_mcp.py:73-80`

- [ ] **Step 1: `CLAUDE.md`, seção `demonstrativos_contabeis`**

Acrescentar `st_conta_fixa ('S' = conta padrão CVM, 'N' = criada pela empresa)` à lista de campos e, logo abaixo das views, o parágrafo:

```markdown
**Períodos no ITR:** no 2T e 3T a DRE tem duas linhas por conta — trimestre isolado
(`dt_ini_exerc` = início do trimestre) e acumulado no ano (`dt_ini_exerc` = início do
exercício). `vw_dre` devolve o trimestre isolado; `vw_dre_acumulada` devolve o acumulado.
DFC_MI e DVA só têm acumulado no ITR. BPA/BPP têm `dt_ini_exerc` NULL (posição na data).
Ao consultar `demonstrativos_contabeis` direto para DRE de ITR, filtre `dt_ini_exerc`,
senão as linhas dobram.
```

Na query "DRE trimestral via view", acrescentar `-- vw_dre = trimestre isolado; use vw_dre_acumulada para o acumulado no ano`.

- [ ] **Step 2: `README.md`**

Nas linhas de `ingest_dfp.py` e `ingest_itr.py` da tabela de fontes, acrescentar à descrição: "trimestre isolado + acumulado; `st_conta_fixa`".

- [ ] **Step 3: `scripts/mcp/cvm_mcp.py`**

No docstring de `query`, trocar `Views: vw_dre, vw_balanco.` por `Views: vw_dre (trimestre isolado no ITR), vw_dre_acumulada, vw_balanco.`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md scripts/mcp/cvm_mcp.py
git commit -m "docs: periodos trimestre/acumulado, st_conta_fixa e vw_dre_acumulada"
```

---

## Fase 1 — Tabelas de achados + Camada 2 (cruzamento entre filings)

> **Plano de tarefas (executado):** `docs/superpowers/plans/2026-09-17-fase1-camada2-cross-period.md`.

### Schema (novo em `schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS consistency_runs (
    run_id          TEXT PRIMARY KEY,
    layer           INTEGER NOT NULL,      -- 1, 2, 3, 5, 6
    check_type      TEXT NOT NULL,
    escopo          TEXT,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    total_checked   INTEGER,
    total_flagged   INTEGER,
    script_args     TEXT                   -- JSON dos argv
);

CREATE TABLE IF NOT EXISTS consistency_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES consistency_runs(run_id),
    layer           INTEGER NOT NULL,
    check_type      TEXT NOT NULL,
    classificacao   TEXT NOT NULL,         -- ver lista por camada abaixo
    severity        TEXT NOT NULL CHECK (severity IN ('info','warn','error')),
    cnpj_companhia  TEXT NOT NULL,
    tipo_doc        TEXT,
    cd_conta        TEXT,
    cd_conta_pai    TEXT,
    ds_conta        TEXT,
    periodo_ini     TEXT,                  -- COALESCE(dt_ini_exerc,'NA')
    periodo_fim     TEXT,
    fonte_ref       TEXT,  data_ref  TEXT, ordem_ref  TEXT,   -- filing de referência (baseline)
    fonte_cmp       TEXT,  data_cmp  TEXT, ordem_cmp  TEXT,   -- filing comparado
    valor_ref       REAL,
    valor_cmp       REAL,
    diff_abs        REAL,
    diff_rel        REAL,
    detalhe         TEXT,                  -- JSON livre (lista de códigos exclusivos, score, etc.)
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cflags_cnpj  ON consistency_flags (cnpj_companhia, periodo_fim DESC);
CREATE INDEX IF NOT EXISTS idx_cflags_class ON consistency_flags (layer, classificacao, severity);
CREATE INDEX IF NOT EXISTS idx_cflags_run   ON consistency_flags (run_id);
```

Diferença para o plano original: `classificacao` e os pares filing-referência/filing-comparado viram colunas (eram JSON em `detalhe`). Consultas via MCP do tipo "quais reapresentações a empresa X fez" não podem depender de parse de JSON.

### Estrutura de arquivos (`scripts/analysis/`, novo)

```
scripts/analysis/
    consistency_utils.py     # parse_hierarchy, normalize_text, text_similarity,
                             #   tolerancia(), latest_rows(conn, ...), new_run(), write_flags()
    check_cross_period.py    # Camada 2 (Fase 1)
    check_hierarchy_sums.py  # Camada 1 (Fase 2)
    check_granularity.py     # Camada 3 (Fase 3)
    check_text_stability.py  # Camadas 4 + 5 (Fase 4)
    derive_quarters.py       # Camada 6 (Fase 5)
    run_all.py               # orquestrador: --layer 1,2,3,5,6 --cnpj --tipo-doc --desde --ate --full
```

Parametrização comum (`argparse`, mesmo estilo de `ingest_dfp.py`): `--cnpj`, `--tipo-doc`, `--desde`/`--ate`, `--full` (confirmação explícita para a base inteira), `--tol-abs` (default 1000.0), `--tol-rel` (default 0.005). Não entra em `update_weekly.sh`.

Helper central, usado por todas as camadas:

```python
def latest_rows(conn, cnpj=None, tipo_doc=None, fonte=None, desde=None, ate=None) -> pd.DataFrame:
    """Linhas de demonstrativos_contabeis na versão máxima **por documento**
    (cnpj, fonte, tipo_doc, data_referencia), com colunas periodo_ini
    (COALESCE(dt_ini_exerc,'NA')) e periodo_fim (dt_fim_exerc)."""
```

### Camada 2 — regras

1. Agrupar `latest_rows` por `(cnpj_companhia, tipo_doc, cd_conta, periodo_ini, periodo_fim)`. Cada grupo tem 1..4 filings (ex: BPA 31/12/Y aparece em DFP(Y).Último e ITR 1T/2T/3T(Y+1).Penúltimo).
2. **Baseline = o filing de menor `data_referencia` do grupo** (o original, como reportado na época). Cada filing posterior é comparado ao baseline; nunca entre si.
3. Antes de comparar linha a linha, classificar o **par de documentos** (`doc_ref`, `doc_cmp`) pelo total de nível 1 do `tipo_doc`:

   | tipo_doc | conta-total |
   |---|---|
   | BPA | `1` |
   | BPP | `2` |
   | DRE | `3.11` e `3.01` (qualquer uma) |
   | DFC_MI | `6.05` |
   | DVA | `7.07` (confirmar com `SELECT DISTINCT cd_conta, ds_conta FROM demonstrativos_contabeis WHERE tipo_doc='DVA' AND cd_conta LIKE '7.0_'` antes de codificar) |

   - total diverge acima da tolerância → par é `reapresentacao` (severity `warn`); toda linha divergente do par herda essa classe.
   - totais batem e alguma linha diverge → linha é `reclassificacao` (severity `info`); a Camada 3 tenta explicar por "Outros"/renumeração e pode promover a `erro`.
   - linha existe num lado e não no outro → não é flag aqui; vai para a Camada 3 com `detalhe = {"exclusivo_em": "ref"|"cmp"}`.
4. Tolerância por linha: `|ref − cmp| > max(tol_abs, tol_rel × |ref|)`.
5. `check_type = 'cross_period'`. Uma flag por linha divergente, mais uma flag por par de documentos com `cd_conta = NULL` resumindo (`detalhe = {"linhas_divergentes": n, "linhas_exclusivas_ref": a, "linhas_exclusivas_cmp": b}`).

### Verificação da Fase 1 (números esperados, medidos em 2026-09-17 na base pré-Fase 0)

| Medida | Esperado |
|---|---|
| Pares BPA DFP(Y) × ITR 1T(Y+1) com alguma divergência | ≈ 38% (669 de 1.746) |
| Desses, classificados `reapresentacao` (ativo total diverge) | ≈ 121 |
| Pares DRE anual DFP(Y) × DFP(Y+1) com divergência | ≈ 38% (639 de 1.687); receita em ≈ 196, lucro em ≈ 113 |
| Linhas BPA exatas entre pareadas | 93–96% |
| **Medido em 2026-09-17, base pós-Fase 0, run `cross_period-20260917T210833Z-e77660`** (tolerância `max(R$ 1.000, 0,5% × \|ref\|)`, 76 s, 36.531 pares, 168.411 flags) | BPA DFP(Y) × ITR 1T(Y+1): **655 de 1.746 (37,5%)** divergentes; `reapresentacao` **75** — com tolerância só absoluta (> R$ 1.000) seriam 121, igual ao esperado: a diferença é o 0,5% relativo. DRE anual DFP × DFP: **638 de 1.641 (38,9%)**; receita (`3.01`) em **156**, lucro (`3.11`) em **94** pares (mesmo efeito da tolerância relativa). Linhas BPA exatas dentro dos pares divergentes: 89,4%. Âncora WEGE3 BPA 2023 DFP × ITR 1T24: 0 flags. Geral: `reapresentacao` 63.768 flags (3.330 pares), `reclassificacao` 104.643 (13.780 pares). |
| **Medido com a tolerância final de 1% relativo** (decisão do usuário; run `cross_period-20260917T211945Z-c54571`, 162.407 flags) | BPA DFP(Y) × ITR 1T(Y+1): 653 de 1.746 (37,4%), `reapresentacao` 59. DRE anual DFP × DFP: 633 (38,6%), receita em 142, lucro em 88. Geral: `reapresentacao` 55.921 flags (2.902 pares), `reclassificacao` 106.486 (14.126 pares). A Camada 2 passou a rodar no `update_weekly.sh` logo após DFP/ITR. |

Se o resultado ficar perto de 0% ou acima de 60%, o agrupamento por período está errado, não os dados. Caso âncora: WEGE3 (`84.429.695/0001-11`), BPA 2023-12-31, DFP × ITR 2024-03-31 Penúltimo → zero flags.

### Testes (mockados, SQLite em memória com `schema.sql`)

- `tests/test_consistency_cross_period.py`: fixtures sintéticas com os 3 pares (BPA anual, DRE trimestral com `periodo_ini` distinto para trimestre e acumulado, DRE anual); caso "total diverge" → `reapresentacao`; caso "só sublinha diverge" → `reclassificacao`; caso "linha exclusiva" → nenhuma flag da Camada 2; baseline é sempre o filing mais antigo mesmo quando o ITR vem antes no DataFrame.

---

## Fase 2 — Camada 1 (soma hierárquica intra-documento)

> **Plano de tarefas (executado):** `docs/superpowers/plans/2026-09-18-fase2-camada1-hierarchy-sums.md`.

### Regras

`parse_hierarchy(codes)`: pai de `X.YY` é `X` (todo segmento tem 2 dígitos após o primeiro; confirmado: 100% das 4,45 M linhas têm `length(cd_conta) % 3 == 1`).

Para cada pai com filhos diretos, na versão máxima do documento, classificar:

| Situação | classificacao | severity |
|---|---|---|
| `\|pai − Σ filhos\| ≤ tol` | (sem flag) | — |
| pai ≠ 0 e todos os filhos são 0 ou NULL | `nao_detalhado` | info |
| pai é 0 ou NULL e algum filho ≠ 0 | `pai_vazio` | warn (0 casos observados; manter porque é o sintoma de ingestão parcial) |
| pai ≠ 0, filhos ≠ 0, diferença > tol | `divergencia` | error |

**Exceções estruturais** (`EXCECOES_SOMA` em `consistency_utils.py`):

```python
EXCECOES_SOMA = {
    ("DFC_MI", "6.05"): "saldo",   # filhos 6.05.01 (saldo inicial) e 6.05.02 (saldo final): 6.05 = 6.05.02 − 6.05.01
    ("DRE", "3.99"):    "skip",    # lucro por ação: filhos ON/PN não somam
}
```

"saldo" é verificado como `|6.05 − (6.05.02 − 6.05.01)| ≤ tol` (bate em 99,8% dos DFPs). "skip" e todos os descendentes de `3.99` são ignorados.

**Fórmulas fixas de nível 2** (substituem a Camada 1B; só para `companies.setor <> 'Financeiro'`):

```python
FORMULAS_NIVEL2 = {
    "DRE":    [("3.03", ["3.01", "3.02"]), ("3.05", ["3.03", "3.04"]), ("3.07", ["3.05", "3.06"]),
               ("3.09", ["3.07", "3.08"]), ("3.11", ["3.09", "3.10"])],
    "DFC_MI": [("6.05", ["6.01", "6.02", "6.03", "6.04"])],
}
```

Acerto medido nos DFPs 2019–2024 não financeiros: 99,8–100% em todas. Filho ausente conta como 0. Falha → `divergencia_formula` (error).

### Verificação da Fase 2

DFP 2023 e 2024, todas as empresas: `nao_detalhado` ≈ 424 em BPA e 423 em BPP; `divergencia` real: BPA 0, BPP 0, DRE ≈ 8, DVA ≈ 3. Qualquer contagem de `divergencia` em BPA/BPP acima de ~10 indica bug no `parse_hierarchy` ou na resolução de versão.

**Medido em 2026-09-18, base pós-Fase 1, run `hierarchy_sum-20260918T103927Z-2abd99`** (tolerância `max(R$ 1.000, 1% × |pai|)`, 26 s, 1.256.194 pais/fórmulas checados em 77.888 grupos documento×ordem×período, 62.682 flags). DFP 2023+2024 `Último`: `nao_detalhado` **424 em BPA e 423 em BPP** (exatamente o esperado), 53 na DRE, 19 na DVA; `divergencia` **BPA 0, BPP 0, DRE 8, DVA 3** (exatamente o esperado); `divergencia_formula` 4 na DRE. Base inteira (todos os filings, ambas as ordens): `nao_detalhado` 62.268 (BPA 24.865, BPP 29.363, DRE 4.311, DVA 3.718, DFC 11); `pai_vazio` 61 (35 na DVA, quase todos de uma empresa em ITR 1T23); `divergencia` 275 (BPA 14, BPP 39, DRE 166, DFC 25, DVA 31) — as de BPA/BPP estão todas em filings ≤ 2022 e têm cara de erro na fonte (ex: FLRY3 ITR 3T22: o desvio de `2.02` é exatamente o desvio de `2`); `divergencia_formula` 78 (DRE 63 em 8 empresas, concentradas em CVCB3 e RECV3 nas fórmulas `3.11` e `3.09`; DFC 15 em 7 empresas). Sem nenhuma flag `pai_vazio`/`divergencia` em BPA/BPP de 2023 em diante: a ingestão pós-Fase 0 está consistente. A Camada 1 passou a rodar no `update_weekly.sh` antes da Camada 2.

### Testes

- `tests/test_consistency_hierarchy.py`: `parse_hierarchy` com `['1','1.01','1.01.01','1.01.02','1.02']`; árvore sintética que bate; `nao_detalhado`; `pai_vazio`; `divergencia`; exceção `6.05` (saldo final − inicial); `3.99` ignorado; fórmula `3.03 = 3.01 + 3.02` com `3.02` negativo; tolerância `max(1000, 0.005·|pai|)`.

---

## Fase 3 — Camada 3 (granularidade entre filings)

> **Plano de tarefas (executado):** `docs/superpowers/plans/2026-09-18-fase3-camada3-granularity.md`. Duas mudanças em relação ao desenho abaixo, medidas no banco: (a) classe nova `reclassificado_em_irmao` (warn) para exclusivas sob pai comum inalterado (10,8 mil linhas — o valor foi absorvido por um irmão nomeado, não por "Outros"); (b) `renumerado` também por valor (`detalhe.casamento = 'valor'`) quando as exclusivas dos dois lados somam o mesmo sem "Outros" envolvido.

Reaproveita os grupos da Camada 2 e recebe as linhas exclusivas (presentes só em `ref` ou só em `cmp`) sob o mesmo `cd_conta_pai`. Ordem de resolução, por pai:

1. **Casamento por nome** entre exclusivos dos dois lados: `normalize_text(ds_conta)` igual → `renumerado` (info), com `detalhe = {"cd_ref": ..., "cd_cmp": ...}`. Depois da Fase 0, também exigir `st_conta_fixa` igual dos dois lados; uma linha `S` ausente do outro lado é uma conta padrão omitida (normalmente zero), não renumeração.
2. Exclusivo restante com `|valor| < tol_abs` → `zero_padding` (info).
3. Restantes: somar os exclusivos não-zero de um lado e comparar com o delta da linha "Outros" do lado oposto entre os **filhos diretos** do mesmo pai. Regex sobre texto normalizado: `r"\b(outr[oa]s?|demais)\b"` (o `\boutr` do plano original casava "outorgadas": 148 linhas no BPP 2024). Bateu → `reclassificado_em_outros` (warn).
4. Não bateu → `divergencia_nao_explicada` (error).

`check_type = 'granularity'`. Casamento por soma agregada (N-para-1), não código a código.

### Verificação da Fase 3

267 docs (15% dos pares BPA DFP × ITR) têm códigos sem par; a maior parte deve sair como `renumerado` ou `zero_padding`. `divergencia_nao_explicada` acima de 20% desses docs indica que o casamento por nome não está normalizando acentos/caixa.

**Medido em 2026-09-18, base pós-Fase 2, run `granularity-20260918T112239Z-e1e9e7`** (64 s, 36.531 pares, 78.031 flags = 66.635 de linha + 11.396 resumos). Pares com exclusivas: 15.396 de 36.531 (BPA 3.120, BPP 3.359, DFC_MI 5.058, DRE 2.513, DVA 1.346); BPA DFP(Y) × ITR 1T(Y+1): **620 de 1.746 (35%)**, não os 267 estimados antes da Fase 0 (a reingestão trouxe as linhas que a chave antiga perdia). Linhas: `zero_padding` **33.258** (50%), `divergencia_nao_explicada` 14.153 (21%; 1.537 no setor Financeiro, só 5 na raiz), `reclassificado_em_irmao` 12.631 (19%), `reclassificado_em_outros` 1.882, `renumerado` 711 (573 por nome, 138 por valor); 2.207 filhos de pai exclusivo sem flag. Dos 620 pares BPA DFP × ITR 1T, 227 (37%) têm `divergencia_nao_explicada` como classe dominante — acima dos 20% do critério acima, mas o casamento por nome está correto (acentos/caixa normalizados; 0 casamentos perdidos por `st_conta_fixa`): o que sobra são reformulações inteiras do plano de contas (bancos) e **renumerações em cascata** (ex: WEG DFC 6.01.02 entre ITR 3T22 e 3T23: os valores de `6.01.02.02…05` deslocam um código; a Camada 2 marca as linhas comuns como `reclassificacao` e a Camada 3 só vê a sobra como exclusiva), que só a Camada 5 (chave por pai + nome, Fase 4) resolve. A Camada 3 passou a rodar no `update_weekly.sh` depois da Camada 2.

### Testes

- `tests/test_consistency_granularity.py`: renumeração (mesmo nome, código diferente); zero-padding; 3 linhas finas viram uma "Outras" no outro lado; divergência real; "Opções outorgadas" não casa o regex.

---

## Fase 4 — Camada 5 (trilha temporal) + Camada 4 (similaridade)

### Schema

```sql
CREATE TABLE IF NOT EXISTS cd_conta_ds_timeline (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia     TEXT NOT NULL,
    tipo_doc           TEXT NOT NULL,
    cd_conta_pai       TEXT NOT NULL,
    ds_conta_norm      TEXT NOT NULL,     -- normalize_text(ds_conta)
    fonte              TEXT NOT NULL,
    data_referencia    TEXT NOT NULL,
    cd_conta           TEXT NOT NULL,
    ds_conta           TEXT,
    st_conta_fixa      TEXT,
    cd_conta_anterior  TEXT,
    ds_conta_anterior  TEXT,
    similarity_score   REAL,
    classificacao      TEXT NOT NULL CHECK (classificacao IN
        ('primeira_ocorrencia','estavel','renumerado','reformulacao','ambiguo','nova','removida')),
    created_at         TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta)
);
CREATE INDEX IF NOT EXISTS idx_timeline_chave ON cd_conta_ds_timeline (cnpj_companhia, tipo_doc, cd_conta_pai, ds_conta_norm);
CREATE INDEX IF NOT EXISTS idx_timeline_class ON cd_conta_ds_timeline (classificacao);
```

Mudança em relação ao original: a **unidade de estabilidade é a linha (pai + nome), não o código**. Só linhas `st_conta_fixa = 'N'` entram na comparação textual; linhas `S` são estáveis por definição da CVM e viram `estavel`/`primeira_ocorrencia` direto.

### Regras (por `(cnpj, tipo_doc, fonte)`, filings consecutivos em `data_referencia`, `ordem_exercicio = 'Último'`)

Para cada pai, comparar o conjunto de filhos diretos do filing anterior (A) com o atual (B):

1. `ds_conta_norm` igual dos dois lados: mesmo código → `estavel` (não grava linha nova); código diferente → `renumerado` (grava, com `cd_conta_anterior`).
2. Sobras de A e B: pareamento guloso por maior `text_similarity` (difflib sobre texto normalizado):
   - score ≥ 0,75 → `reformulacao`
   - 0,45 < score < 0,75 → `ambiguo` (fila de revisão manual; guardar score)
   - score ≤ 0,45 ou sem par → linha de B é `nova`, linha de A é `removida`
3. Primeiro filing de cada linha → `primeira_ocorrencia`.

Limiares vêm da distribuição medida em 12.773 mudanças reais de DFC_MI (bimodal: massas em 0,2–0,4 e 0,8–1,0, 13% na zona 0,5–0,7). Depois de rodar na base, revisar ~50 `ambiguo` à mão e ajustar os dois cortes; registrar a decisão neste arquivo.

### Verificação da Fase 4

DFC_MI, DFP: ≈ 12,8 mil mudanças de nome; ≈ 3,6 mil (28%) devem sair como `renumerado`; ≈ 968 somem porque só mudam caixa/acento (normalização). Pergunta-alvo via MCP: "quantas linhas da DFC da empresa X foram renumeradas, reformuladas ou removidas nos últimos 5 anos".

### Testes

- `tests/test_consistency_text.py`: `normalize_text` (acento, caixa, pontuação, espaços); `text_similarity` com pares conhecidos ("Obrigações pós emprego" × "Obrigação de benefício pós-emprego" ≈ 0,75; "Partes relacionadas" × "Fornecedores" ≈ 0,19); casamento por pai que produz `renumerado`; `S` nunca entra em `ambiguo`.

---

## Fase 5 — Camada 6 (desacúmulo) + `demonstrativos_trimestrais`

### Schema

```sql
CREATE TABLE IF NOT EXISTS demonstrativos_trimestrais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia  TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL CHECK (tipo_doc IN ('DRE','DFC_MI','DVA')),
    safra           TEXT NOT NULL CHECK (safra IN ('original','reapresentado')),
    dt_ini_exerc    TEXT NOT NULL,
    dt_fim_exerc    TEXT NOT NULL,
    trimestre       INTEGER NOT NULL CHECK (trimestre BETWEEN 1 AND 4),  -- posição no exercício social, não no ano-calendário
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_publicado    REAL,        -- linha trimestral do ITR (só DRE 1T–3T)
    vl_derivado     REAL,        -- acum(Qn) − acum(Qn−1), ou DFP − acum(3T) no 4T
    origem          TEXT NOT NULL CHECK (origem IN ('publicado','derivado')),  -- qual valor vale para vl_final
    vl_final        REAL,
    flag            TEXT CHECK (flag IN ('reapresentacao_intra_ano','componente_reapresentado','sem_3t','sem_dfp')),
    fonte_a         TEXT, data_a TEXT, ordem_a TEXT,   -- filing do minuendo
    fonte_b         TEXT, data_b TEXT, ordem_b TEXT,   -- filing do subtraendo (NULL no 1T)
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, tipo_doc, safra, dt_fim_exerc, cd_conta)
);
```

### Regras

| Caso | `vl_final` | Verificação | Flag |
|---|---|---|---|
| DRE 1T–3T | `vl_publicado` (linha com `dt_ini_exerc` = início do trimestre) | `vl_derivado = acum(Qn) − acum(Qn−1)`, ambos acumulados de ITR da mesma safra | `\|publicado − derivado\| > tol` → `reapresentacao_intra_ano` |
| DRE 4T | derivado: `DFP(Y).Último − ITR 3T(Y).Último acumulado` (safra original) e `DFP(Y+1).Penúltimo − ITR 3T(Y+1).Penúltimo acumulado` (safra reapresentado) | — | se um componente tem flag `reapresentacao` na Camada 2 → `componente_reapresentado` |
| DFC_MI e DVA, todos os trimestres | derivado (não há publicado) | 4T: `6.05` derivado deve bater com a variação de caixa (`1.01.01` do BPA entre 30/09 e 31/12) | fora da tolerância → `reapresentacao_intra_ano` |
| Sem ITR 3T ou sem DFP | não deriva | — | `sem_3t` / `sem_dfp` |

Regra de safra: **os dois operandos vêm sempre de filings da mesma safra**. `safra = 'original'` usa só `Último`; `safra = 'reapresentado'` usa só `Penúltimo` de filings do exercício seguinte. Exercício social não encerrado em dezembro funciona igual: `trimestre` é calculado a partir de `dt_ini_exerc` do exercício, não do mês-calendário.

`derive_quarters.py` repopula a tabela por empresa (`DELETE` + `INSERT` por `(cnpj, tipo_doc, safra)`), e grava as flags também em `consistency_flags` com `layer = 6`.

### Verificação da Fase 5

Só é medível depois da Fase 0 (a base atual não tem os acumulados de 2T/3T). Expectativa, pelo que os pares anuais mostraram: 10–20% dos docs com `reapresentacao_intra_ano`. WEGE3 2024: 1T 8.033 mi, 2T 9.274 mi, 3T 9.857 mi (publicados) e 4T = DFP 2024 (37.987 mi) − acumulado 3T.

### Testes

- `tests/test_derive_quarters.py`: fixture com 1T/2T/3T acumulados + DFP; 2T publicado ≠ derivado → flag; 4T = DFP − 3T; DFC só derivado; safra reapresentada usa só `Penúltimo`; exercício com início em abril produz `trimestre = 1` para abril–junho.

---

## Verificação geral

- `pytest tests/` mockado, sem tocar `cvm_research.db`.
- Toda fase aplica `schema.sql` num banco temporário antes do banco real.
- Depois de cada `run_all.py --layer N --full`, checar via MCP: `SELECT layer, classificacao, severity, COUNT(*) FROM consistency_flags GROUP BY 1,2,3` e comparar com as tabelas "Verificação" de cada fase.
- Queries usadas na revisão de 2026-09-17 (`t1.sql`…`tH.sql`, `tG.py`) ficaram no scratchpad da sessão; os números esperados acima são a referência.

## Arquivos críticos

- `schema.sql` — Fase 0 (tabela, `ux_dem_periodo`, views), Fase 1 (`consistency_*`), Fase 4 (`cd_conta_ds_timeline`), Fase 5 (`demonstrativos_trimestrais`)
- `scripts/migrations/2026-09-17_dem_contabeis_periodo.sql` — Fase 0
- `scripts/ingest/utils.py`, `scripts/ingest/ingest_dfp.py`, `scripts/ingest/ingest_itr.py` — Fase 0
- `scripts/analysis/` — Fases 1–5 (diretório novo)
- `tests/test_ingest_periodo.py`, `tests/test_consistency_*.py`, `tests/test_derive_quarters.py`
- `CLAUDE.md`, `README.md`, `scripts/mcp/cvm_mcp.py` — documentação a cada fase
