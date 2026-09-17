# Fase 1 — Tabelas de achados + Camada 2 (cruzamento entre filings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Expande a seção "Fase 1" do plano-mãe `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` em tarefas com código, seguindo o precedente da Fase 0 daquele arquivo. Pré-requisito: Fase 0 aplicada no banco real (confirmado em 2026-09-17: `ux_dem_periodo` existe, `st_conta_fixa` preenchido em 4,7M linhas, ITR 3T tem 4 `dt_ini_exerc` distintos por documento).

**Goal:** Criar `consistency_runs` + `consistency_flags` e a Camada 2, que compara cada período contábil entre os filings que o carregam (DFP × ITRs seguintes × DFP seguinte), usando o filing mais antigo como baseline e classificando divergências em `reapresentacao` (total diverge) ou `reclassificacao` (só sublinhas divergem).

**Architecture:** Scripts standalone em `scripts/analysis/` (fora de `update_weekly.sh`) que só leem `demonstrativos_contabeis` e gravam em tabelas próprias. `consistency_utils.py` concentra o acesso ao banco (`latest_rows`, `new_run`, `write_flags`, `clear_flags`) e a tolerância; `check_cross_period.py` tem a lógica pura da Camada 2 em funções testáveis com `DataFrame` (sem banco) mais um `main()` que percorre a base empresa a empresa. Flags são idempotentes por `(cnpj, tipo_doc)`: cada execução apaga as flags anteriores desse escopo antes de gravar; `consistency_runs` guarda o histórico.

**Tech Stack:** Python 3.14 (`.venv`), `pandas` 2.2, `numpy` (dependência do pandas), `sqlite3` 3.50, `pytest` 8.3.

---

## Decisões de desenho verificadas contra o banco (2026-09-17)

| Ponto | O que a base mostra | Decisão |
|---|---|---|
| Quantos filings carregam o mesmo período | BPA 2023-12-31 da WEG aparece em 5 filings: DFP 2023 Último, ITR 1T/2T/3T 2024 Penúltimo, DFP 2024 Penúltimo. DRE 2T23 (trimestre e acumulado) aparece em ITR 2T23 Último e ITR 2T24 Penúltimo, com `dt_ini_exerc` distinto por período. | Agrupar por `(cnpj, tipo_doc, periodo_ini, periodo_fim)`; baseline = menor `data_referencia`; desempate por `fonte`, `ordem_exercicio` (determinístico, na prática nunca empata). |
| Conta-total da DVA | `7.07` = "Valor Adicionado Total a Distribuir" em 6.867 docs, mas `7.08` em 150 (bancos) e `7.10` em 94 (seguradoras). | `total_codes('DVA', doc)` resolve pelo nome nas contas de nível 2 do próprio documento; fallback `7.07`. |
| Conta-total da DRE | `3.01` e `3.11` existem em todos os planos (industrial, bancos, seguradoras), com nomes diferentes. | Lista fixa `['3.11', '3.01']`; qualquer uma divergindo ⇒ `reapresentacao`. |
| Volume por empresa | Máximo 54.512 linhas por CNPJ (média 32.446). | `main()` processa um CNPJ por vez com `latest_rows(conn, cnpj=...)`; nunca carrega a base inteira em memória. |
| `vl_conta` NULL | A CVM deixa `vl_conta` vazio em linhas estruturais. | NULL conta como 0 na comparação (`valor_ref`/`valor_cmp` gravados como 0.0). |
| Caso âncora | WEGE3 BPA 2023-12-31, DFP × ITR 2024-03-31 Penúltimo: 68 pares de contas, 0 divergentes. | Teste de fumaça da Task 6. |
| Como o schema chega ao banco real | `setup.sh` roda `sqlite3 cvm_research.db < schema.sql`; tudo é `IF NOT EXISTS`. | Sem arquivo de migração: Task 1 aplica `schema.sql` direto (idempotente). |

## Estrutura de arquivos

- **Modify:** `schema.sql` — seção nova `-- ── 8. consistência` com `consistency_runs`, `consistency_flags` e 3 índices (antes da seção `-- ── Views`).
- **Create:** `scripts/analysis/consistency_utils.py` — `get_db` (reexportado de `scripts/ingest/utils.py`), `tolerancia`, `parent_code`, `total_codes`, `latest_rows`, `new_run`, `finish_run`, `write_flags`, `clear_flags`, `add_common_args`.
- **Create:** `scripts/analysis/check_cross_period.py` — `compare_pair` (um par de documentos, um período), `check_cross_period` (um `DataFrame` de `latest_rows` → flags + stats), `main` (CLI, loop por CNPJ).
- **Create:** `scripts/analysis/run_all.py` — orquestrador `--layer 2` (registro de camadas; cresce nas fases seguintes).
- **Create:** `tests/test_consistency_utils.py`, `tests/test_consistency_cross_period.py` — SQLite em memória com `schema.sql` (mesmo padrão de `tests/test_ingest_periodo.py`).
- **Modify:** `CLAUDE.md` (subseção `consistency_flags` + query padrão "Reapresentações"), `README.md` (estrutura + seção "Análise de consistência"), `scripts/mcp/cvm_mcp.py` (docstring de `query`), plano-mãe (ponteiro para este arquivo na seção Fase 1).

Convenção de import: os scripts rodam com `cd scripts/analysis` (como `scripts/ingest`); os testes inserem `scripts/analysis` no `sys.path`, como `tests/test_ingest_periodo.py` faz com `scripts/ingest`.

---

### Task 0: Branch de trabalho

**Files:** nenhum.

Worktree não serve aqui: `.env` e `cvm_research.db` (12 GB) ficam fora do git e o `.venv` é relativo à raiz. Trabalhar num branch no mesmo diretório.

- [ ] **Step 1: Criar o branch a partir de `main` limpo**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git status --short && git checkout -b fase-1-camada-2
```

Expected: `git status --short` vazio; `Switched to a new branch 'fase-1-camada-2'`.

---

### Task 1: Schema — `consistency_runs` e `consistency_flags`

**Files:**
- Modify: `schema.sql` (inserir antes da linha `-- ── Views ───`)

- [ ] **Step 1: Adicionar a seção ao `schema.sql`**

Inserir imediatamente antes de `-- ── Views ─────` (a linha que abre a seção das views, logo depois da `CREATE VIRTUAL TABLE ... notas_explicativas_fts`):

```sql
-- ── 8. Consistência de dados financeiros ─────────────────────────────────────
-- Achados dos scripts de scripts/analysis/ (fora do job semanal). Nunca alteram
-- demonstrativos_contabeis: o valor publicado pela CVM é intocável; aqui ficam
-- os metadados (reapresentação, reclassificação, etc.) linha a linha.
-- Camadas: 2 = cruzamento entre filings (Fase 1); 1 = soma hierárquica (Fase 2);
-- 3 = granularidade (Fase 3); 4/5 = texto (Fase 4); 6 = desacúmulo (Fase 5).

CREATE TABLE IF NOT EXISTS consistency_runs (
    run_id          TEXT PRIMARY KEY,
    layer           INTEGER NOT NULL,      -- 1, 2, 3, 5, 6
    check_type      TEXT NOT NULL,         -- ex: 'cross_period'
    escopo          TEXT,                  -- 'full' ou 'cnpj=... tipo_doc=... desde=... ate=...'
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    total_checked   INTEGER,               -- unidades checadas (Camada 2: pares documento×período)
    total_flagged   INTEGER,
    script_args     TEXT                   -- JSON dos argumentos do script
);

-- Uma flag por linha divergente; linhas com cd_conta NULL são o resumo do par
-- de documentos (detalhe JSON com contagens). Flags são substituídas por
-- (layer, check_type, cnpj_companhia[, tipo_doc]) a cada execução — a tabela
-- reflete sempre a última execução de cada escopo; o histórico fica em runs.
CREATE TABLE IF NOT EXISTS consistency_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES consistency_runs(run_id),
    layer           INTEGER NOT NULL,
    check_type      TEXT NOT NULL,
    classificacao   TEXT NOT NULL,         -- Camada 2: 'reapresentacao' | 'reclassificacao'
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'error')),
    cnpj_companhia  TEXT NOT NULL,
    tipo_doc        TEXT,
    cd_conta        TEXT,                  -- NULL = resumo do par de documentos
    cd_conta_pai    TEXT,
    ds_conta        TEXT,
    periodo_ini     TEXT,                  -- COALESCE(dt_ini_exerc, 'NA')
    periodo_fim     TEXT,                  -- dt_fim_exerc
    fonte_ref       TEXT,  data_ref  TEXT, ordem_ref  TEXT,   -- filing de referência (baseline)
    fonte_cmp       TEXT,  data_cmp  TEXT, ordem_cmp  TEXT,   -- filing comparado
    valor_ref       REAL,
    valor_cmp       REAL,
    diff_abs        REAL,                  -- valor_cmp − valor_ref
    diff_rel        REAL,                  -- diff_abs / |valor_ref| (NULL se valor_ref = 0)
    detalhe         TEXT,                  -- JSON livre
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cflags_cnpj  ON consistency_flags (cnpj_companhia, periodo_fim DESC);
CREATE INDEX IF NOT EXISTS idx_cflags_class ON consistency_flags (layer, classificacao, severity);
CREATE INDEX IF NOT EXISTS idx_cflags_run   ON consistency_flags (run_id);

```

- [ ] **Step 2: Validar o schema num banco vazio**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && rm -f /tmp/cvm_schema_check.db && sqlite3 /tmp/cvm_schema_check.db < schema.sql && sqlite3 /tmp/cvm_schema_check.db ".tables" && sqlite3 /tmp/cvm_schema_check.db "PRAGMA table_info(consistency_flags);" | wc -l && rm /tmp/cvm_schema_check.db
```

Expected: a lista de tabelas inclui `consistency_flags` e `consistency_runs`; o `wc -l` responde `25` (colunas).

- [ ] **Step 3: Aplicar no banco real (idempotente)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 cvm_research.db < schema.sql && sqlite3 -readonly cvm_research.db "SELECT name FROM sqlite_master WHERE name LIKE 'consistency%' OR name LIKE 'idx_cflags%' ORDER BY 1;"
```

Expected: 5 linhas (`consistency_flags`, `consistency_runs`, `idx_cflags_class`, `idx_cflags_cnpj`, `idx_cflags_run`). Nenhum erro — todo o `schema.sql` é `IF NOT EXISTS`.

- [ ] **Step 4: Rodar a suíte existente (as views não mudaram, mas o arquivo sim)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q
```

Expected: tudo PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add schema.sql && git commit -m "feat(schema): consistency_runs e consistency_flags (Fase 1, achados de consistência)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `consistency_utils.py` — tolerância, hierarquia e conta-total

**Files:**
- Create: `scripts/analysis/consistency_utils.py`
- Create: `tests/test_consistency_utils.py`

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_consistency_utils.py`:

```python
"""
Fase 1 da consistência financeira: helpers compartilhados (scripts/analysis/consistency_utils.py).
"""
import json
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import consistency_utils as cu

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _insert(conn, rows):
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    conn.commit()


def _row(**kw):
    base = {"cnpj_companhia": CNPJ, "fonte": "DFP", "tipo_doc": "BPA", "data_referencia": "2023-12-31",
            "versao": 1, "ordem_exercicio": "Último", "dt_ini_exerc": None, "dt_fim_exerc": "2023-12-31",
            "cd_conta": "1", "ds_conta": "Ativo Total", "vl_conta": 10.0, "st_conta_fixa": "S"}
    base.update(kw)
    return base


# ── tolerancia / parent_code / total_codes ───────────────────────────────────

def test_tolerancia_piso_absoluto_e_relativo():
    assert cu.tolerancia(0.0) == 1000.0
    assert cu.tolerancia(100_000.0) == 1000.0            # 0,5% = 500 < piso
    assert cu.tolerancia(1_000_000_000.0) == 5_000_000.0  # 0,5% de 1 bi
    assert cu.tolerancia(-1_000_000_000.0) == 5_000_000.0
    assert cu.tolerancia(100_000.0, tol_abs=10.0, tol_rel=0.01) == 1000.0


def test_tolerancia_aceita_series():
    s = pd.Series([0.0, 1_000_000_000.0, -200_000.0])
    got = cu.tolerancia(s)
    assert list(got) == [1000.0, 5_000_000.0, 1000.0]


def test_parent_code():
    assert cu.parent_code("3.04.05.06") == "3.04.05"
    assert cu.parent_code("3.01") == "3"
    assert cu.parent_code("1") is None


def test_total_codes_fixos_por_tipo_doc():
    vazio = pd.DataFrame(columns=["cd_conta", "ds_conta"])
    assert cu.total_codes("BPA", vazio) == ["1"]
    assert cu.total_codes("BPP", vazio) == ["2"]
    assert cu.total_codes("DRE", vazio) == ["3.11", "3.01"]
    assert cu.total_codes("DFC_MI", vazio) == ["6.05"]


def test_total_codes_dva_resolve_pelo_nome():
    banco = pd.DataFrame([
        {"cd_conta": "7.07", "ds_conta": "Vlr Adicionado Recebido em Transferência"},
        {"cd_conta": "7.08", "ds_conta": "Valor Adicionado Total a Distribuir"},
        {"cd_conta": "7.08.01", "ds_conta": "Pessoal"},
        {"cd_conta": "7.06.03.02", "ds_conta": "Valor Adicionado Total a Distribuir"},  # nível 4: ignorar
    ])
    assert cu.total_codes("DVA", banco) == ["7.08"]
    sem_nome = pd.DataFrame([{"cd_conta": "7.07", "ds_conta": None}])
    assert cu.total_codes("DVA", sem_nome) == ["7.07"]


# ── latest_rows ──────────────────────────────────────────────────────────────

def test_latest_rows_versao_maxima_por_documento_e_periodo_na():
    conn = _db()
    _insert(conn, [_row(versao=1, vl_conta=10.0), _row(versao=2, vl_conta=11.0),
                   _row(versao=2, cd_conta="1.01", ds_conta="Ativo Circulante", vl_conta=6.0)])
    df = cu.latest_rows(conn, cnpj=CNPJ)
    assert len(df) == 2
    assert set(df["versao"]) == {2}
    assert df.loc[df["cd_conta"] == "1", "vl_conta"].item() == 11.0
    assert set(df["periodo_ini"]) == {"NA"}
    assert set(df["periodo_fim"]) == {"2023-12-31"}


def test_latest_rows_filtros():
    conn = _db()
    _insert(conn, [
        _row(),
        _row(cnpj_companhia="00.000.000/0001-91"),
        _row(tipo_doc="DRE", dt_ini_exerc="2023-01-01"),
        _row(data_referencia="2021-12-31", dt_fim_exerc="2021-12-31"),
        _row(fonte="ITR", data_referencia="2024-03-31", ordem_exercicio="Penúltimo"),
    ])
    assert len(cu.latest_rows(conn)) == 5
    assert len(cu.latest_rows(conn, cnpj=CNPJ)) == 4
    assert len(cu.latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA")) == 3
    assert len(cu.latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA", desde=2023)) == 2
    assert len(cu.latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA", desde=2023, ate=2023)) == 1
    assert len(cu.latest_rows(conn, fonte="ITR")) == 1
    dre = cu.latest_rows(conn, tipo_doc="DRE")
    assert dre["periodo_ini"].item() == "2023-01-01"


def test_latest_rows_vazio_tem_colunas():
    df = cu.latest_rows(_db(), cnpj="nenhum")
    assert df.empty
    assert {"periodo_ini", "periodo_fim", "cd_conta", "vl_conta"} <= set(df.columns)


# ── runs / flags ─────────────────────────────────────────────────────────────

def test_new_run_finish_run_e_write_flags_roundtrip():
    conn = _db()
    run_id = cu.new_run(conn, layer=2, check_type="cross_period", escopo="cnpj=" + CNPJ,
                        script_args={"cnpj": CNPJ, "tol_abs": 1000.0})
    assert run_id.startswith("cross_period-")
    run = conn.execute("SELECT layer, check_type, escopo, started_at, finished_at, script_args "
                       "FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run[0] == 2 and run[1] == "cross_period" and run[2] == "cnpj=" + CNPJ
    assert run[3] is not None and run[4] is None
    assert json.loads(run[5]) == {"cnpj": CNPJ, "tol_abs": 1000.0}

    n = cu.write_flags(conn, run_id, [
        {"layer": 2, "check_type": "cross_period", "classificacao": "reapresentacao", "severity": "warn",
         "cnpj_companhia": CNPJ, "tipo_doc": "BPA", "cd_conta": "1", "cd_conta_pai": None,
         "ds_conta": "Ativo Total", "periodo_ini": "NA", "periodo_fim": "2023-12-31",
         "fonte_ref": "DFP", "data_ref": "2023-12-31", "ordem_ref": "Último",
         "fonte_cmp": "ITR", "data_cmp": "2024-03-31", "ordem_cmp": "Penúltimo",
         "valor_ref": 100.0, "valor_cmp": 110.0, "diff_abs": 10.0, "diff_rel": 0.1,
         "detalhe": {"linhas_divergentes": 1}},
        {"layer": 2, "check_type": "cross_period", "classificacao": "reclassificacao", "severity": "info",
         "cnpj_companhia": CNPJ, "tipo_doc": "BPA", "cd_conta": None,
         "valor_ref": float("nan"), "diff_rel": None},   # NaN vira NULL; chaves ausentes viram NULL
    ])
    assert n == 2
    assert cu.write_flags(conn, run_id, []) == 0
    got = conn.execute("SELECT cd_conta, valor_ref, diff_rel, detalhe, fonte_cmp FROM consistency_flags "
                       "WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    assert got[0] == ("1", 100.0, 0.1, '{"linhas_divergentes": 1}', "ITR")
    assert got[1] == (None, None, None, None, None)

    cu.finish_run(conn, run_id, total_checked=7, total_flagged=2)
    run = conn.execute("SELECT finished_at, total_checked, total_flagged FROM consistency_runs "
                       "WHERE run_id = ?", (run_id,)).fetchone()
    assert run[0] is not None and run[1] == 7 and run[2] == 2


def test_write_flags_rejeita_severity_invalida():
    conn = _db()
    run_id = cu.new_run(conn, 2, "cross_period", "x", {})
    with pytest.raises(sqlite3.IntegrityError):
        cu.write_flags(conn, run_id, [{"layer": 2, "check_type": "cross_period", "classificacao": "x",
                                       "severity": "fatal", "cnpj_companhia": CNPJ}])


def test_clear_flags_por_cnpj_e_tipo_doc():
    conn = _db()
    run_id = cu.new_run(conn, 2, "cross_period", "x", {})
    base = {"layer": 2, "check_type": "cross_period", "classificacao": "reclassificacao", "severity": "info"}
    cu.write_flags(conn, run_id, [
        {**base, "cnpj_companhia": CNPJ, "tipo_doc": "BPA"},
        {**base, "cnpj_companhia": CNPJ, "tipo_doc": "DRE"},
        {**base, "cnpj_companhia": "00.000.000/0001-91", "tipo_doc": "BPA"},
        {**base, "layer": 1, "check_type": "hierarchy", "cnpj_companhia": CNPJ, "tipo_doc": "BPA"},
    ])
    assert cu.clear_flags(conn, 2, "cross_period", CNPJ, tipo_doc="BPA") == 1
    assert cu.clear_flags(conn, 2, "cross_period", CNPJ) == 1          # sobrou a DRE
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 2


# ── add_common_args ──────────────────────────────────────────────────────────

def test_add_common_args_defaults_e_parse():
    import argparse
    p = argparse.ArgumentParser()
    cu.add_common_args(p)
    a = p.parse_args([])
    assert (a.cnpj, a.tipo_doc, a.desde, a.ate, a.full, a.tol_abs, a.tol_rel) == \
        (None, None, None, None, False, 1000.0, 0.005)
    a = p.parse_args(["--cnpj", CNPJ, "--tipo-doc", "DFC_MI", "--desde", "2020", "--ate", "2024",
                      "--tol-abs", "500", "--tol-rel", "0.01"])
    assert (a.cnpj, a.tipo_doc, a.desde, a.ate, a.tol_abs, a.tol_rel) == \
        (CNPJ, "DFC_MI", 2020, 2024, 500.0, 0.01)
    with pytest.raises(SystemExit):
        p.parse_args(["--tipo-doc", "XYZ"])
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_utils.py -q 2>&1 | tail -5
```

Expected: erro de coleta `ModuleNotFoundError: No module named 'consistency_utils'`.

- [ ] **Step 3: Implementar `scripts/analysis/consistency_utils.py` completo**

```python
"""
Helpers compartilhados pelas camadas de consistência (scripts/analysis/).

Convenções:
  - Nunca alteram demonstrativos_contabeis: leem dela e gravam apenas em
    consistency_runs / consistency_flags.
  - "Documento" (filing) = (cnpj_companhia, fonte, tipo_doc, data_referencia)
    na versão máxima. "Período" = (periodo_ini, periodo_fim), com
    periodo_ini = COALESCE(dt_ini_exerc, 'NA') — BPA/BPP são posição na data.
  - Tolerância por linha: max(tol_abs, tol_rel × |ref|), piso R$ 1.000
    (plano-mãe: na DRE o piso sobe o acerto de 81% para 87,6%).
"""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from utils import get_db  # noqa: E402  — reaproveita DATABASE_URL, WAL e foreign_keys

__all__ = ["get_db", "tolerancia", "parent_code", "total_codes", "latest_rows",
           "new_run", "finish_run", "write_flags", "clear_flags", "add_common_args",
           "TIPOS_DOC", "FLAG_COLS"]

TIPOS_DOC = ["BPA", "BPP", "DRE", "DFC_MI", "DVA"]

# Conta-total de nível 1/2 por tipo_doc (plano-mãe, Camada 2, regra 3).
# DRE: 3.01 e 3.11 existem em todos os planos de contas; qualquer uma divergindo
# classifica o par como reapresentação.
# DVA: o código varia por plano (7.07 industrial, 7.08 bancos, 7.10 seguradoras);
# total_codes() resolve pelo nome dentro do próprio documento.
TOTAL_CODES = {
    "BPA":    ["1"],
    "BPP":    ["2"],
    "DRE":    ["3.11", "3.01"],
    "DFC_MI": ["6.05"],
    "DVA":    ["7.07"],
}
DVA_TOTAL_DS = "valor adicionado total a distribuir"


# ── Regras numéricas ─────────────────────────────────────────────────────────

def tolerancia(valor_ref, tol_abs: float = 1000.0, tol_rel: float = 0.005):
    """max(tol_abs, tol_rel × |valor_ref|). Aceita escalar ou pd.Series (sem NaN)."""
    return np.maximum(tol_abs, tol_rel * np.abs(valor_ref))


def parent_code(cd_conta: str):
    """'3.04.05.06' → '3.04.05'; '1' → None."""
    return cd_conta.rsplit(".", 1)[0] if "." in cd_conta else None


def total_codes(tipo_doc: str, doc: pd.DataFrame) -> list[str]:
    """Códigos da conta-total do tipo_doc. Para DVA procura o nome nas contas de
    nível 2 do documento (`doc` precisa das colunas cd_conta e ds_conta)."""
    if tipo_doc != "DVA":
        return TOTAL_CODES[tipo_doc]
    nivel2 = doc[doc["cd_conta"].astype(str).str.count(r"\.") == 1]
    nomes = nivel2["ds_conta"].fillna("").astype(str).str.strip().str.lower()
    achados = nivel2.loc[nomes.str.startswith(DVA_TOTAL_DS), "cd_conta"].unique().tolist()
    return achados or TOTAL_CODES["DVA"]


# ── Leitura ──────────────────────────────────────────────────────────────────

_LATEST_SQL = """
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE 1 = 1 {filtros}
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia
)
SELECT d.cnpj_companhia, d.fonte, d.tipo_doc, d.data_referencia, d.versao,
       d.ordem_exercicio,
       COALESCE(d.dt_ini_exerc, 'NA') AS periodo_ini,
       d.dt_fim_exerc                 AS periodo_fim,
       d.cd_conta, d.ds_conta, d.vl_conta, d.st_conta_fixa
FROM demonstrativos_contabeis d
JOIN versao_max v
  ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
  AND d.tipo_doc = v.tipo_doc AND d.data_referencia = v.data_referencia
  AND d.versao = v.versao
ORDER BY d.cnpj_companhia, d.tipo_doc, d.data_referencia, d.fonte, d.ordem_exercicio, d.cd_conta
"""


def latest_rows(conn: sqlite3.Connection, cnpj=None, tipo_doc=None, fonte=None,
                desde=None, ate=None) -> pd.DataFrame:
    """Linhas de demonstrativos_contabeis na versão máxima **por documento**
    (cnpj, fonte, tipo_doc, data_referencia), com periodo_ini/periodo_fim.
    desde/ate são anos e filtram a data_referencia do FILING — um filing de
    `desde` ainda carrega períodos Penúltimo do ano anterior."""
    filtros, params = [], []
    if cnpj:
        filtros.append("AND cnpj_companhia = ?"); params.append(cnpj)
    if tipo_doc:
        filtros.append("AND tipo_doc = ?"); params.append(tipo_doc)
    if fonte:
        filtros.append("AND fonte = ?"); params.append(fonte)
    if desde:
        filtros.append("AND data_referencia >= ?"); params.append(f"{desde}-01-01")
    if ate:
        filtros.append("AND data_referencia <= ?"); params.append(f"{ate}-12-31")
    sql = _LATEST_SQL.format(filtros=" ".join(filtros))
    return pd.read_sql_query(sql, conn, params=params)


# ── Escrita (runs / flags) ───────────────────────────────────────────────────

FLAG_COLS = [
    "run_id", "layer", "check_type", "classificacao", "severity",
    "cnpj_companhia", "tipo_doc", "cd_conta", "cd_conta_pai", "ds_conta",
    "periodo_ini", "periodo_fim",
    "fonte_ref", "data_ref", "ordem_ref", "fonte_cmp", "data_cmp", "ordem_cmp",
    "valor_ref", "valor_cmp", "diff_abs", "diff_rel", "detalhe",
]


def new_run(conn, layer: int, check_type: str, escopo: str, script_args: dict) -> str:
    run_id = f"{check_type}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO consistency_runs (run_id, layer, check_type, escopo, script_args) VALUES (?,?,?,?,?)",
        (run_id, layer, check_type, escopo, json.dumps(script_args, ensure_ascii=False, default=str)),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id: str, total_checked: int, total_flagged: int) -> None:
    conn.execute(
        "UPDATE consistency_runs SET finished_at = datetime('now'), total_checked = ?, total_flagged = ? "
        "WHERE run_id = ?",
        (total_checked, total_flagged, run_id),
    )
    conn.commit()


def _sql_value(v):
    """NaN/numpy → tipos nativos/NULL; dict/list → JSON."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    return v


def write_flags(conn, run_id: str, flags: list[dict]) -> int:
    """Insere flags (dicts com chaves de FLAG_COLS; ausentes viram NULL). Retorna n."""
    if not flags:
        return 0
    rows = [tuple(_sql_value(run_id if c == "run_id" else f.get(c)) for c in FLAG_COLS) for f in flags]
    sql = (f"INSERT INTO consistency_flags ({','.join(FLAG_COLS)}) "
           f"VALUES ({','.join('?' * len(FLAG_COLS))})")
    try:
        conn.executemany(sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def clear_flags(conn, layer: int, check_type: str, cnpj: str, tipo_doc: str | None = None) -> int:
    """Apaga as flags anteriores do escopo (layer, check_type, cnpj[, tipo_doc]). Retorna n."""
    sql = "DELETE FROM consistency_flags WHERE layer = ? AND check_type = ? AND cnpj_companhia = ?"
    params: list = [layer, check_type, cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        params.append(tipo_doc)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


# ── CLI ──────────────────────────────────────────────────────────────────────

def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Argumentos comuns a todas as camadas (mesmo estilo de ingest_dfp.py)."""
    parser.add_argument("--cnpj", help="CNPJ no formato 00.000.000/0001-00 (só essa empresa)")
    parser.add_argument("--tipo-doc", dest="tipo_doc", choices=TIPOS_DOC, help="Só esse tipo de demonstrativo")
    parser.add_argument("--desde", type=int, metavar="ANO", help="data_referencia do filing >= ANO-01-01")
    parser.add_argument("--ate", type=int, metavar="ANO", help="data_referencia do filing <= ANO-12-31")
    parser.add_argument("--full", action="store_true", help="Confirma a execução na base inteira (sem --cnpj)")
    parser.add_argument("--tol-abs", dest="tol_abs", type=float, default=1000.0,
                        help="Tolerância absoluta em R$ (padrão 1000)")
    parser.add_argument("--tol-rel", dest="tol_rel", type=float, default=0.005,
                        help="Tolerância relativa sobre |ref| (padrão 0.005 = 0,5%%)")
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_utils.py -v 2>&1 | tail -20
```

Expected: 12 PASS. Se `test_total_codes_fixos_por_tipo_doc` falhar com `KeyError` no DataFrame vazio, é porque `doc["cd_conta"]` de um `DataFrame(columns=[...])` tem dtype object — o `.astype(str)` cobre isso; conferir que a implementação está idêntica.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/consistency_utils.py tests/test_consistency_utils.py && git commit -m "feat(analysis): consistency_utils — latest_rows por documento, tolerancia, runs e flags

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `check_cross_period.py` — lógica pura da Camada 2

**Files:**
- Create: `scripts/analysis/check_cross_period.py`
- Create: `tests/test_consistency_cross_period.py`

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_consistency_cross_period.py`:

```python
"""
Fase 1 da consistência financeira: Camada 2 (cruzamento entre filings).
Testa a lógica pura (DataFrame → flags), sem banco.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_cross_period as ccp

CNPJ = "84.429.695/0001-11"
BPA = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 60e6), "1.02": ("Ativo Não Circulante", 40e6)}


def _doc(fonte, data_ref, ordem, p_ini, p_fim, contas, tipo_doc="BPA"):
    """Linhas de um documento para UM período, no formato de latest_rows."""
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": p_ini, "periodo_fim": p_fim,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": vl, "st_conta_fixa": "S"}
            for cd, (ds, vl) in contas.items()]


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


def _dfp23(contas=BPA):
    return _doc("DFP", "2023-12-31", "Último", "NA", "2023-12-31", contas)


def _itr1t24(contas=BPA):
    return _doc("ITR", "2024-03-31", "Penúltimo", "NA", "2023-12-31", contas)


def _resumos(flags):
    return [f for f in flags if f["cd_conta"] is None]


def _linhas(flags):
    return [f for f in flags if f["cd_conta"] is not None]


def test_pares_iguais_nao_geram_flags():
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24()))
    assert flags == []
    assert stats == {"BPA": {"pares": 1, "pares_divergentes": 0, "reapresentacao": 0}}


def test_dataframe_vazio():
    assert ccp.check_cross_period(pd.DataFrame()) == ([], {})


def test_total_diverge_e_reapresentacao_warn():
    cmp = {"1": ("Ativo Total", 110e6), "1.01": ("Ativo Circulante", 70e6), "1.02": ("Ativo Não Circulante", 40e6)}
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert stats["BPA"] == {"pares": 1, "pares_divergentes": 1, "reapresentacao": 1}
    assert {f["classificacao"] for f in flags} == {"reapresentacao"}
    assert {f["severity"] for f in flags} == {"warn"}
    linhas = {f["cd_conta"]: f for f in _linhas(flags)}
    assert set(linhas) == {"1", "1.01"}
    total = linhas["1"]
    assert (total["layer"], total["check_type"], total["cnpj_companhia"], total["tipo_doc"]) == \
        (2, "cross_period", CNPJ, "BPA")
    assert (total["periodo_ini"], total["periodo_fim"]) == ("NA", "2023-12-31")
    assert (total["fonte_ref"], total["data_ref"], total["ordem_ref"]) == ("DFP", "2023-12-31", "Último")
    assert (total["fonte_cmp"], total["data_cmp"], total["ordem_cmp"]) == ("ITR", "2024-03-31", "Penúltimo")
    assert (total["valor_ref"], total["valor_cmp"], total["diff_abs"]) == (100e6, 110e6, 10e6)
    assert abs(total["diff_rel"] - 0.1) < 1e-12
    assert total["ds_conta"] == "Ativo Total" and total["cd_conta_pai"] is None
    assert linhas["1.01"]["cd_conta_pai"] == "1"
    resumo, = _resumos(flags)
    assert resumo["classificacao"] == "reapresentacao" and resumo["severity"] == "warn"
    assert resumo["fonte_cmp"] == "ITR" and resumo["periodo_fim"] == "2023-12-31"
    assert resumo["detalhe"] == {"linhas_comuns": 3, "linhas_divergentes": 2,
                                 "linhas_exclusivas_ref": 0, "linhas_exclusivas_cmp": 0,
                                 "total_disponivel": True}


def test_sublinha_diverge_e_reclassificacao_info():
    cmp = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 61e6), "1.02": ("Ativo Não Circulante", 39e6)}
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert stats["BPA"] == {"pares": 1, "pares_divergentes": 1, "reapresentacao": 0}
    assert {f["classificacao"] for f in flags} == {"reclassificacao"}
    assert {f["severity"] for f in flags} == {"info"}
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.01", "1.02"}
    assert _resumos(flags)[0]["detalhe"]["linhas_divergentes"] == 2


def test_linha_exclusiva_nao_gera_flag_de_linha():
    cmp = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 60e6), "1.03": ("Outros", 40e6)}
    flags, _ = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert flags == []                       # só exclusivas: Camada 3 cuida; nada aqui
    cmp["1.01"] = ("Ativo Circulante", 62e6)
    flags, _ = ccp.check_cross_period(_df(_dfp23(), _itr1t24(cmp)))
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.01"}
    assert _resumos(flags)[0]["detalhe"] == {"linhas_comuns": 2, "linhas_divergentes": 1,
                                             "linhas_exclusivas_ref": 1, "linhas_exclusivas_cmp": 1,
                                             "total_disponivel": True}


def test_baseline_e_o_filing_mais_antigo_mesmo_com_itr_primeiro():
    itr_div = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 65e6), "1.02": ("Ativo Não Circulante", 35e6)}
    dfp24 = _doc("DFP", "2024-12-31", "Penúltimo", "NA", "2023-12-31", BPA)
    flags, stats = ccp.check_cross_period(_df(_itr1t24(itr_div), dfp24, _dfp23()))
    assert stats["BPA"] == {"pares": 2, "pares_divergentes": 1, "reapresentacao": 0}
    assert {(f["fonte_ref"], f["data_ref"]) for f in flags} == {("DFP", "2023-12-31")}
    assert {(f["fonte_cmp"], f["data_cmp"]) for f in flags} == {("ITR", "2024-03-31")}


def test_dre_trimestre_e_acumulado_nao_se_misturam():
    acu = {"3.01": ("Receita", 200e6), "3.11": ("Lucro", 20e6)}
    tri = {"3.01": ("Receita", 120e6), "3.11": ("Lucro", 12e6)}
    df = _df(
        _doc("ITR", "2023-06-30", "Último",    "2023-01-01", "2023-06-30", acu, "DRE"),
        _doc("ITR", "2023-06-30", "Último",    "2023-04-01", "2023-06-30", tri, "DRE"),
        _doc("ITR", "2024-06-30", "Penúltimo", "2023-01-01", "2023-06-30", acu, "DRE"),
        _doc("ITR", "2024-06-30", "Penúltimo", "2023-04-01", "2023-06-30", tri, "DRE"),
    )
    flags, stats = ccp.check_cross_period(df)
    assert flags == []
    assert stats == {"DRE": {"pares": 2, "pares_divergentes": 0, "reapresentacao": 0}}


def test_dre_qualquer_total_divergente_classifica_reapresentacao():
    ref = {"3.01": ("Receita", 200e6), "3.05": ("EBIT", 30e6), "3.11": ("Lucro", 20e6)}
    cmp = {"3.01": ("Receita", 200e6), "3.05": ("EBIT", 30e6), "3.11": ("Lucro", 25e6)}
    df = _df(_doc("DFP", "2023-12-31", "Último",    "2023-01-01", "2023-12-31", ref, "DRE"),
             _doc("DFP", "2024-12-31", "Penúltimo", "2023-01-01", "2023-12-31", cmp, "DRE"))
    flags, stats = ccp.check_cross_period(df)
    assert stats["DRE"]["reapresentacao"] == 1
    assert {f["cd_conta"] for f in _linhas(flags)} == {"3.11"}
    assert {f["classificacao"] for f in flags} == {"reapresentacao"}


def test_dva_total_resolvido_pelo_nome_do_documento():
    ref = {"7.07": ("Vlr Adicionado Recebido em Transferência", 1e6), "7.08": ("Valor Adicionado Total a Distribuir", 50e6)}
    cmp = {"7.07": ("Vlr Adicionado Recebido em Transferência", 1e6), "7.08": ("Valor Adicionado Total a Distribuir", 55e6)}
    df = _df(_doc("DFP", "2023-12-31", "Último",    "2023-01-01", "2023-12-31", ref, "DVA"),
             _doc("DFP", "2024-12-31", "Penúltimo", "2023-01-01", "2023-12-31", cmp, "DVA"))
    flags, stats = ccp.check_cross_period(df)
    assert stats["DVA"]["reapresentacao"] == 1


def test_tolerancia_piso_e_relativa():
    ref = {"1": ("Ativo Total", 1e9), "1.01": ("Ativo Circulante", 100_000.0), "1.02": ("Ativo Não Circulante", 100_000.0)}
    cmp = {"1": ("Ativo Total", 1e9 + 4e6),             # 0,4% < 0,5%
           "1.01": ("Ativo Circulante", 100_900.0),       # +900 < piso 1000
           "1.02": ("Ativo Não Circulante", 101_100.0)}   # +1100 > piso
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)))
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.02"}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)), tol_abs=500.0)
    assert {f["cd_conta"] for f in _linhas(flags)} == {"1.01", "1.02"}


def test_vl_conta_nulo_conta_como_zero():
    ref = {"1": ("Ativo Total", 100e6), "1.02": ("Ativo Não Circulante", None)}
    cmp = {"1": ("Ativo Total", 100e6), "1.02": ("Ativo Não Circulante", 5e6)}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)))
    linha, = _linhas(flags)
    assert (linha["cd_conta"], linha["valor_ref"], linha["valor_cmp"], linha["diff_abs"], linha["diff_rel"]) == \
        ("1.02", 0.0, 5e6, 5e6, None)


def test_total_ausente_dos_dois_lados_vira_reclassificacao_sem_total():
    ref = {"1.01": ("Ativo Circulante", 60e6)}
    cmp = {"1.01": ("Ativo Circulante", 70e6)}
    flags, _ = ccp.check_cross_period(_df(_dfp23(ref), _itr1t24(cmp)))
    assert {f["classificacao"] for f in flags} == {"reclassificacao"}
    assert _resumos(flags)[0]["detalhe"]["total_disponivel"] is False


def test_empresas_e_tipos_nao_se_cruzam():
    outra = [dict(r, cnpj_companhia="00.000.000/0001-91", vl_conta=r["vl_conta"] * 2) for r in _itr1t24()]
    bpp = _doc("DFP", "2023-12-31", "Último", "NA", "2023-12-31", {"2": ("Passivo Total", 100e6)}, "BPP")
    flags, stats = ccp.check_cross_period(_df(_dfp23(), _itr1t24(), outra, bpp))
    assert flags == []
    assert stats == {"BPA": {"pares": 1, "pares_divergentes": 0, "reapresentacao": 0}}
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_cross_period.py -q 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'check_cross_period'`.

- [ ] **Step 3: Implementar a lógica pura em `scripts/analysis/check_cross_period.py`**

(O `main()` entra na Task 4; por enquanto o arquivo termina em `check_cross_period`.)

```python
"""
Camada 2 — cruzamento entre filings (check_type = 'cross_period').

O mesmo período contábil aparece em até 5 filings: o BPA de 31/12/Y está no
DFP(Y).Último, nos ITRs 1T/2T/3T(Y+1).Penúltimo e no DFP(Y+1).Penúltimo; a
DRE do 2T de Y (trimestre e acumulado, dt_ini_exerc distinto) está no
ITR 2T(Y).Último e no ITR 2T(Y+1).Penúltimo.

Esta camada agrupa as linhas por (cnpj, tipo_doc, periodo_ini, periodo_fim),
toma como baseline o filing de menor data_referencia (o original, como
reportado na época) e compara cada filing posterior ao baseline — nunca
filings posteriores entre si.

Classificação do PAR (documento_ref, documento_cmp, período), pela conta-total
do tipo_doc (consistency_utils.total_codes):
  - total diverge acima da tolerância → 'reapresentacao' (warn); toda linha
    divergente do par herda a classe;
  - totais batem e alguma linha diverge → 'reclassificacao' (info);
  - linha que existe só num lado não gera flag aqui (Camada 3, Fase 3); entra
    apenas nas contagens do resumo do par.
Tolerância por linha: |cmp − ref| > max(tol_abs, tol_rel × |ref|); NULL = 0.

Saída: uma flag por linha divergente + uma flag-resumo por par (cd_conta NULL)
com detalhe = {linhas_comuns, linhas_divergentes, linhas_exclusivas_ref,
linhas_exclusivas_cmp, total_disponivel}. Pares sem linha divergente não geram
flag. Flags anteriores do mesmo (cnpj[, tipo_doc]) são apagadas antes de gravar.

Uso (na pasta scripts/analysis, .venv ativo):
  python check_cross_period.py --cnpj 84.429.695/0001-11
  python check_cross_period.py --cnpj 84.429.695/0001-11 --tipo-doc BPA --desde 2023
  python check_cross_period.py --full            # base inteira (~145 empresas, ~1 min)
"""
import pandas as pd

from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows,
                               new_run, parent_code, tolerancia, total_codes, write_flags)

LAYER = 2
CHECK_TYPE = "cross_period"
SEVERITY = {"reapresentacao": "warn", "reclassificacao": "info"}
DOC_COLS = ["data_referencia", "fonte", "ordem_exercicio"]   # ordem = critério de baseline
GROUP_COLS = ["cnpj_companhia", "tipo_doc", "periodo_ini", "periodo_fim"]
RESUMO_KEYS = ["linhas_comuns", "linhas_divergentes", "linhas_exclusivas_ref",
               "linhas_exclusivas_cmp", "total_disponivel"]


def compare_pair(ref: pd.DataFrame, cmp: pd.DataFrame, tipo_doc: str,
                 tol_abs: float = 1000.0, tol_rel: float = 0.005) -> tuple[list[dict], dict]:
    """Compara as linhas de UM período em dois documentos (já filtradas).

    Retorna (flags_de_linha, resumo). As flags vêm só com os campos da linha
    (cd_conta, valores, classificacao, severity); o chamador acrescenta o
    contexto do par (cnpj, período, documentos).
    """
    # merge interno + diferença de conjuntos (indicator=True dispara FutureWarning
    # dentro do pandas 2.2 e não acrescenta nada aqui)
    comuns = ref[["cd_conta", "ds_conta", "vl_conta"]].merge(
        cmp[["cd_conta", "ds_conta", "vl_conta"]], on="cd_conta", how="inner",
        suffixes=("_ref", "_cmp"),
    )
    codigos_ref, codigos_cmp = set(ref["cd_conta"]), set(cmp["cd_conta"])
    v_ref = comuns["vl_conta_ref"].astype(float).fillna(0.0)
    v_cmp = comuns["vl_conta_cmp"].astype(float).fillna(0.0)
    divergentes = comuns[(v_cmp - v_ref).abs() > tolerancia(v_ref, tol_abs, tol_rel)]

    totais = total_codes(tipo_doc, ref)
    total_disponivel = bool(comuns["cd_conta"].isin(totais).any())
    classe = "reapresentacao" if divergentes["cd_conta"].isin(totais).any() else "reclassificacao"

    resumo = {
        "classificacao": classe,
        "linhas_comuns": int(len(comuns)),
        "linhas_divergentes": int(len(divergentes)),
        "linhas_exclusivas_ref": len(codigos_ref - codigos_cmp),
        "linhas_exclusivas_cmp": len(codigos_cmp - codigos_ref),
        "total_disponivel": total_disponivel,
    }
    flags = []
    for r in divergentes.itertuples(index=False):
        ref_v = 0.0 if pd.isna(r.vl_conta_ref) else float(r.vl_conta_ref)
        cmp_v = 0.0 if pd.isna(r.vl_conta_cmp) else float(r.vl_conta_cmp)
        flags.append({
            "cd_conta": r.cd_conta,
            "cd_conta_pai": parent_code(r.cd_conta),
            "ds_conta": r.ds_conta_ref if not pd.isna(r.ds_conta_ref) else r.ds_conta_cmp,
            "valor_ref": ref_v,
            "valor_cmp": cmp_v,
            "diff_abs": cmp_v - ref_v,
            "diff_rel": (cmp_v - ref_v) / abs(ref_v) if ref_v else None,
            "classificacao": classe,
            "severity": SEVERITY[classe],
        })
    return flags, resumo


def _doc_rows(grupo: pd.DataFrame, doc) -> pd.DataFrame:
    mask = ((grupo["data_referencia"] == doc.data_referencia)
            & (grupo["fonte"] == doc.fonte)
            & (grupo["ordem_exercicio"] == doc.ordem_exercicio))
    return grupo[mask]


def check_cross_period(df: pd.DataFrame, tol_abs: float = 1000.0,
                       tol_rel: float = 0.005) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"pares": n, "pares_divergentes": m, "reapresentacao": k},
    contando pares (documento_ref, documento_cmp, período).
    Linhas com periodo_fim NULL são ignoradas (groupby descarta NaN na chave).
    """
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return flags, stats
    for (cnpj, tipo_doc, p_ini, p_fim), grupo in df.groupby(GROUP_COLS, sort=True):
        docs = list(grupo[DOC_COLS].drop_duplicates().sort_values(DOC_COLS).itertuples(index=False))
        if len(docs) < 2:
            continue
        st = stats.setdefault(tipo_doc, {"pares": 0, "pares_divergentes": 0, "reapresentacao": 0})
        ref_doc = docs[0]
        ref = _doc_rows(grupo, ref_doc)
        for cmp_doc in docs[1:]:
            st["pares"] += 1
            linhas, resumo = compare_pair(ref, _doc_rows(grupo, cmp_doc), tipo_doc, tol_abs, tol_rel)
            if resumo["linhas_divergentes"] == 0:
                continue
            st["pares_divergentes"] += 1
            if resumo["classificacao"] == "reapresentacao":
                st["reapresentacao"] += 1
            contexto = {
                "layer": LAYER, "check_type": CHECK_TYPE,
                "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
                "periodo_ini": p_ini, "periodo_fim": p_fim,
                "fonte_ref": ref_doc.fonte, "data_ref": ref_doc.data_referencia, "ordem_ref": ref_doc.ordem_exercicio,
                "fonte_cmp": cmp_doc.fonte, "data_cmp": cmp_doc.data_referencia, "ordem_cmp": cmp_doc.ordem_exercicio,
            }
            flags.extend({**contexto, **linha} for linha in linhas)
            flags.append({
                **contexto,
                "cd_conta": None,
                "classificacao": resumo["classificacao"],
                "severity": SEVERITY[resumo["classificacao"]],
                "detalhe": {k: resumo[k] for k in RESUMO_KEYS},
            })
    return flags, stats
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_cross_period.py -v 2>&1 | tail -20
```

Expected: 13 PASS.

Armadilhas conhecidas se algo falhar:
- `test_vl_conta_nulo_conta_como_zero`: `vl_conta` com `None` num `DataFrame` misto vira `object`; o `.astype(float)` antes do `.fillna(0.0)` resolve. Não inverter a ordem.
- `test_baseline_e_o_filing_mais_antigo...`: o baseline vem de `sort_values(DOC_COLS)` — `data_referencia` é string ISO, ordena lexicograficamente certo.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/check_cross_period.py tests/test_consistency_cross_period.py && git commit -m "feat(analysis): Camada 2 cross_period — baseline por periodo, reapresentacao vs reclassificacao

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: CLI de `check_cross_period.py` + `run_all.py`

**Files:**
- Modify: `scripts/analysis/check_cross_period.py` (acrescentar `main()` ao final)
- Create: `scripts/analysis/run_all.py`
- Modify: `tests/test_consistency_cross_period.py` (teste de `main` com banco em memória via monkeypatch)

- [ ] **Step 1: Escrever o teste que falha (ponta a ponta, banco em memória)**

Acrescentar ao final de `tests/test_consistency_cross_period.py`:

```python
# ── main(): ponta a ponta com banco em memória ───────────────────────────────

import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db_com_docs():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    cmp = {"1": ("Ativo Total", 110e6), "1.01": ("Ativo Circulante", 70e6), "1.02": ("Ativo Não Circulante", 40e6)}
    rows = _dfp23() + _itr1t24(cmp)
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols) for r in rows],
    )
    conn.commit()
    return conn


def test_main_grava_run_e_flags_e_substitui_anteriores(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(ccp, "get_db", lambda: conn)

    run1 = ccp.main(["--cnpj", CNPJ])
    n1 = conn.execute("SELECT COUNT(*) FROM consistency_flags WHERE run_id = ?", (run1,)).fetchone()[0]
    assert n1 == 3                                              # 2 linhas + 1 resumo
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, finished_at "
                       "FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (2, "cross_period", f"cnpj={CNPJ}", 1, 3) and run[5] is not None

    run2 = ccp.main(["--cnpj", CNPJ, "--tipo-doc", "BPA"])
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 3   # substituiu, não somou
    assert conn.execute("SELECT DISTINCT run_id FROM consistency_flags").fetchone()[0] == run2
    assert conn.execute("SELECT COUNT(*) FROM consistency_runs").fetchone()[0] == 2

    out = capsys.readouterr().out
    assert "BPA" in out and "pares=1" in out and "reapresentacao=1" in out


def test_main_exige_cnpj_ou_full(monkeypatch):
    monkeypatch.setattr(ccp, "get_db", lambda: _db_com_docs())
    import pytest
    with pytest.raises(SystemExit):
        ccp.main([])


def test_main_full_percorre_companies(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(ccp, "get_db", lambda: conn)
    run_id = ccp.main(["--full"])
    escopo = conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert escopo == "full"
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 3
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_cross_period.py -q -k main 2>&1 | tail -5
```

Expected: 3 FAIL com `AttributeError: module 'check_cross_period' has no attribute 'main'`.

- [ ] **Step 3: Acrescentar `main()` ao final de `scripts/analysis/check_cross_period.py`**

```python


# ── CLI ──────────────────────────────────────────────────────────────────────

def _escopo(args) -> str:
    if not args.cnpj and not args.tipo_doc and not args.desde and not args.ate:
        return "full"
    partes = [f"cnpj={args.cnpj}" if args.cnpj else None,
              f"tipo_doc={args.tipo_doc}" if args.tipo_doc else None,
              f"desde={args.desde}" if args.desde else None,
              f"ate={args.ate}" if args.ate else None]
    return " ".join(p for p in partes if p)


def main(argv=None) -> str:
    """Roda a Camada 2 e devolve o run_id. `argv=None` lê sys.argv."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args(argv)
    if not args.cnpj and not args.full:
        parser.error("informe --cnpj ou confirme a base inteira com --full")

    conn = get_db()
    if args.cnpj:
        cnpjs = [args.cnpj]
    else:
        cnpjs = [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
    run_id = new_run(conn, LAYER, CHECK_TYPE, _escopo(args), vars(args))
    print(f"run {run_id}: {len(cnpjs)} empresa(s), tol_abs={args.tol_abs} tol_rel={args.tol_rel}")

    total_checked = total_flagged = 0
    stats_total: dict = {}
    for i, cnpj in enumerate(cnpjs, 1):
        df = latest_rows(conn, cnpj=cnpj, tipo_doc=args.tipo_doc, desde=args.desde, ate=args.ate)
        flags, stats = check_cross_period(df, args.tol_abs, args.tol_rel)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_flags(conn, run_id, flags)
        pares = sum(s["pares"] for s in stats.values())
        total_checked += pares
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {"pares": 0, "pares_divergentes": 0, "reapresentacao": 0})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {pares} pares, {n} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print(f"\nResumo por tipo_doc (pares = documento_ref × documento_cmp × período):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        pct = 100.0 * s["pares_divergentes"] / s["pares"] if s["pares"] else 0.0
        print(f"  {tipo:7s} pares={s['pares']} divergentes={s['pares_divergentes']} ({pct:.1f}%) "
              f"reapresentacao={s['reapresentacao']}")
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Criar `scripts/analysis/run_all.py`**

```python
"""
Orquestrador das camadas de consistência (scripts/analysis/).

  python run_all.py --layer 2 --cnpj 84.429.695/0001-11
  python run_all.py --layer 2 --full

Os demais argumentos (--cnpj, --tipo-doc, --desde, --ate, --full, --tol-abs,
--tol-rel) são repassados ao script de cada camada. Camadas disponíveis
crescem a cada fase do plano (1 = soma hierárquica, 3 = granularidade,
5 = trilha temporal, 6 = desacúmulo). Não entra em update_weekly.sh.
"""
import argparse
import sys

import check_cross_period

LAYERS = {
    2: check_cross_period.main,
}


def main(argv=None) -> list[str]:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layer", required=True,
                        help="Camadas a rodar, separadas por vírgula (disponíveis: "
                             + ",".join(str(k) for k in sorted(LAYERS)) + ")")
    args, resto = parser.parse_known_args(argv)
    layers = [int(x) for x in args.layer.split(",")]
    desconhecidas = [l for l in layers if l not in LAYERS]
    if desconhecidas:
        parser.error(f"camada(s) não implementada(s): {desconhecidas}")
    run_ids = []
    for layer in layers:
        print(f"\n═══ Camada {layer} ═══")
        run_ids.append(LAYERS[layer](resto))
    return run_ids


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Rodar todos os testes**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: tudo PASS (suíte anterior + 12 utils + 16 cross_period).

- [ ] **Step 6: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/check_cross_period.py scripts/analysis/run_all.py tests/test_consistency_cross_period.py && git commit -m "feat(analysis): CLI de check_cross_period (loop por CNPJ, flags idempotentes) e run_all --layer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Fumaça no banco real — caso âncora WEGE3

**Files:** nenhum (só execução).

- [ ] **Step 1: Conferir a premissa de `periodo_fim` não nulo**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -readonly cvm_research.db "SELECT COUNT(*) FROM demonstrativos_contabeis WHERE dt_fim_exerc IS NULL;"
```

Expected: `0`. Se não for zero, essas linhas são ignoradas pela Camada 2 (documentado na docstring de `check_cross_period`); anotar a contagem no commit da Task 7.

- [ ] **Step 2: Rodar a Camada 2 só para a WEG**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && ../../.venv/bin/python run_all.py --layer 2 --cnpj 84.429.695/0001-11
```

Expected: uma linha `[1/1] 84.429.695/0001-11: ~35000 linhas, N pares, M flags` e o resumo por tipo_doc (BPA, BPP, DRE, DFC_MI, DVA). Sem traceback.

- [ ] **Step 3: Verificar o caso âncora e a forma das flags**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -readonly -header cvm_research.db "SELECT COUNT(*) AS ancora_deve_ser_0 FROM consistency_flags WHERE cnpj_companhia='84.429.695/0001-11' AND tipo_doc='BPA' AND periodo_fim='2023-12-31' AND fonte_cmp='ITR' AND data_cmp='2024-03-31'; SELECT tipo_doc, classificacao, severity, COUNT(*) n FROM consistency_flags WHERE cnpj_companhia='84.429.695/0001-11' GROUP BY 1,2,3 ORDER BY 1,2; SELECT tipo_doc, cd_conta, ds_conta, periodo_ini, periodo_fim, fonte_ref, data_ref, fonte_cmp, data_cmp, valor_ref, valor_cmp, diff_rel, classificacao FROM consistency_flags WHERE cnpj_companhia='84.429.695/0001-11' AND cd_conta IS NOT NULL ORDER BY periodo_fim DESC, tipo_doc LIMIT 15; SELECT tipo_doc, periodo_fim, fonte_cmp, data_cmp, detalhe FROM consistency_flags WHERE cnpj_companhia='84.429.695/0001-11' AND cd_conta IS NULL ORDER BY periodo_fim DESC LIMIT 10;"
```

Expected: `ancora_deve_ser_0 = 0`. As demais queries são inspeção manual: os `detalhe` são JSON com as 5 chaves; `periodo_ini` = `NA` em BPA/BPP e data em DRE/DFC/DVA; `fonte_ref`/`data_ref` sempre ≤ `data_cmp`. Se aparecer alguma linha com `data_ref > data_cmp`, o baseline está errado — parar e revisar `DOC_COLS`.

- [ ] **Step 4: Verificar a idempotência (rodar de novo não duplica)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && ../../.venv/bin/python check_cross_period.py --cnpj 84.429.695/0001-11 --tipo-doc DRE >/dev/null && sqlite3 -readonly ../../cvm_research.db "SELECT tipo_doc, COUNT(DISTINCT run_id) runs, COUNT(*) n FROM consistency_flags WHERE cnpj_companhia='84.429.695/0001-11' GROUP BY 1;"
```

Expected: `DRE` com `runs = 1` (o run novo) e os outros tipos com `runs = 1` (o run anterior, intocado). Contagem de DRE igual à da execução anterior.

---

### Task 6: Execução completa e verificação dos números esperados

**Files:** nenhum (só execução). Referência: tabela "Verificação da Fase 1" do plano-mãe (números medidos pré-Fase 0; esperar ordem de grandeza, não igualdade).

- [ ] **Step 1: Rodar a base inteira**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && time ../../.venv/bin/python run_all.py --layer 2 --full 2>&1 | tail -12
```

Expected: 145 empresas processadas, resumo por tipo_doc, `total_flagged` na casa de dezenas de milhares. Tempo esperado: 1–5 min.

- [ ] **Step 2: Distribuição geral (checar via MCP ou sqlite3)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -readonly -header cvm_research.db "SELECT layer, classificacao, severity, COUNT(*) n, SUM(cd_conta IS NULL) resumos FROM consistency_flags GROUP BY 1,2,3;"
```

Expected: só `layer = 2`; duas classes (`reapresentacao`/`warn`, `reclassificacao`/`info`).

- [ ] **Step 3: Pares BPA DFP(Y) × ITR 1T(Y+1) — esperado ≈ 38% divergentes (669 de 1.746), ≈ 121 reapresentações**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -readonly -header cvm_research.db "
WITH pares AS (
  SELECT DISTINCT a.cnpj_companhia, a.data_referencia AS data_ref
  FROM demonstrativos_contabeis a
  JOIN demonstrativos_contabeis b
    ON b.cnpj_companhia = a.cnpj_companhia AND b.tipo_doc = 'BPA' AND b.fonte = 'ITR'
   AND b.ordem_exercicio = 'Penúltimo' AND b.dt_fim_exerc = a.data_referencia
   AND b.data_referencia = (CAST(substr(a.data_referencia, 1, 4) AS INTEGER) + 1) || '-03-31'
  WHERE a.tipo_doc = 'BPA' AND a.fonte = 'DFP' AND a.ordem_exercicio = 'Último' AND a.cd_conta = '1'
),
div AS (
  SELECT cnpj_companhia, data_ref, classificacao
  FROM consistency_flags
  WHERE layer = 2 AND tipo_doc = 'BPA' AND cd_conta IS NULL
    AND fonte_ref = 'DFP' AND fonte_cmp = 'ITR' AND substr(data_cmp, 6) = '03-31'
)
SELECT COUNT(*) AS pares_total,
       SUM(d.classificacao IS NOT NULL) AS pares_divergentes,
       ROUND(100.0 * SUM(d.classificacao IS NOT NULL) / COUNT(*), 1) AS pct,
       SUM(d.classificacao = 'reapresentacao') AS reapresentacoes
FROM pares p LEFT JOIN div d USING (cnpj_companhia, data_ref);"
```

Expected: `pct` entre 25 e 50; `reapresentacoes` na casa de 100–150. Fora de 0–60% ⇒ agrupamento por período errado (não os dados) — parar e revisar `GROUP_COLS`/`latest_rows`.

- [ ] **Step 4: DRE anual DFP(Y) × DFP(Y+1) — esperado ≈ 38% (639 de 1.687); receita em ≈ 196, lucro em ≈ 113**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -readonly -header cvm_research.db "
SELECT COUNT(*) AS pares_divergentes,
       SUM(classificacao = 'reapresentacao') AS reapresentacoes
FROM consistency_flags
WHERE layer = 2 AND tipo_doc = 'DRE' AND cd_conta IS NULL AND fonte_ref = 'DFP' AND fonte_cmp = 'DFP';
SELECT cd_conta, COUNT(*) AS pares_com_linha_divergente
FROM consistency_flags
WHERE layer = 2 AND tipo_doc = 'DRE' AND cd_conta IN ('3.01', '3.11') AND fonte_ref = 'DFP' AND fonte_cmp = 'DFP'
GROUP BY 1;"
```

Expected: `pares_divergentes` ≈ 500–800; `3.01` ≈ 150–250; `3.11` ≈ 80–150.

- [ ] **Step 5: Linhas BPA exatas entre pareadas — esperado 93–96%**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -readonly -header cvm_research.db "
SELECT ROUND(100.0 * (1 - SUM(json_extract(detalhe, '$.linhas_divergentes')) * 1.0 / SUM(json_extract(detalhe, '$.linhas_comuns'))), 1) AS pct_linhas_exatas_nos_pares_divergentes
FROM consistency_flags WHERE layer = 2 AND tipo_doc = 'BPA' AND cd_conta IS NULL AND fonte_ref = 'DFP' AND fonte_cmp = 'ITR' AND substr(data_cmp, 6) = '03-31';"
```

Expected: esse número é só sobre pares divergentes (os pares exatos não geram resumo), então fica abaixo dos 93–96% globais — algo como 60–85%. Serve para detectar um bug grosseiro (ex: 0% = todas as linhas divergindo = escala ou período errado).

- [ ] **Step 6: Registrar os números medidos no plano-mãe**

Em `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md`, seção "Verificação da Fase 1", acrescentar ao final da tabela uma linha por medida com o valor **medido** (ex: `| Medido em 2026-09-17 (pós-Fase 0, run <run_id>) | BPA 1T: X de Y (Z%), reapres. W; DRE anual: ... |`). Sem código — é registro.

- [ ] **Step 7: Commit do registro**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md && git commit -m "docs(plano): numeros medidos da Camada 2 na base pos-Fase 0

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Documentação

**Files:**
- Modify: `CLAUDE.md` (nova subseção depois de `### notas_explicativas`, antes de `---` / `## Queries de pesquisa padrão`; nova query padrão depois de "DRE linha a linha")
- Modify: `README.md` (árvore em "Estrutura do projeto"; nova seção "Análise de consistência" antes de "## Histórico")
- Modify: `scripts/mcp/cvm_mcp.py` (docstring de `query`, linhas 73–80)
- Modify: `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` (ponteiro na seção Fase 1)

- [ ] **Step 1: `CLAUDE.md` — subseção da tabela**

Inserir logo depois do parágrafo final da seção `### notas_explicativas` (o que termina em "...descarta o `texto_extraido` da versão anterior."), antes da linha `---`:

```markdown
### `consistency_flags` — achados de consistência dos demonstrativos (metadados, não valores)
`run_id, layer, check_type, classificacao, severity ('info'/'warn'/'error'), cnpj_companhia, tipo_doc,`
`cd_conta (NULL = resumo do par de documentos), cd_conta_pai, ds_conta, periodo_ini ('NA' em BPA/BPP), periodo_fim,`
`fonte_ref, data_ref, ordem_ref (filing baseline), fonte_cmp, data_cmp, ordem_cmp (filing comparado),`
`valor_ref, valor_cmp, diff_abs (cmp − ref), diff_rel, detalhe (JSON)`

Gerada por `scripts/analysis/` (fora do job semanal; rodar à mão depois de reingerir DFP/ITR).
Nunca altera `demonstrativos_contabeis`: o valor publicado pela CVM fica intacto e aqui ficam os metadados.
A tabela guarda **a última execução de cada escopo** `(layer, check_type, cnpj[, tipo_doc])`; o histórico
de execuções está em `consistency_runs` (`run_id, layer, check_type, escopo, started_at, finished_at,
total_checked, total_flagged, script_args`).

**Camada 2 (`layer = 2`, `check_type = 'cross_period'`)** — o mesmo período aparece em até 5 filings
(BPA 31/12/Y: DFP(Y) Último, ITR 1T/2T/3T(Y+1) Penúltimo, DFP(Y+1) Penúltimo). O baseline é sempre o
filing mais antigo (o original, como reportado na época) e cada filing posterior é comparado a ele:
- `reapresentacao` (`warn`): a conta-total do tipo_doc (`1`, `2`, `3.01`/`3.11`, `6.05`, "Valor Adicionado
  Total a Distribuir") diverge acima da tolerância `max(R$ 1.000, 0,5% × |ref|)`; todas as linhas
  divergentes do par herdam a classe.
- `reclassificacao` (`info`): totais batem, mas alguma sublinha diverge (mudou de conta).
- Linha que existe só num dos filings **não** gera flag (Camada 3, futura); só entra nas contagens do
  resumo do par (`detalhe = {"linhas_comuns", "linhas_divergentes", "linhas_exclusivas_ref",
  "linhas_exclusivas_cmp", "total_disponivel"}`).

Para rodar: `cd scripts/analysis && python run_all.py --layer 2 --cnpj <CNPJ>` (ou `--full` para a base).

```

- [ ] **Step 2: `CLAUDE.md` — query padrão**

Inserir depois da query "DRE linha a linha (quando a view não tiver a conta que você quer)" e antes de "### Busca full-text":

```markdown
### Reapresentações e reclassificações de uma empresa (Camada 2)
```sql
-- Resumo por par de filings: quais períodos foram reapresentados e por quem
SELECT tipo_doc, periodo_ini, periodo_fim,
       fonte_ref || ' ' || data_ref AS baseline,
       fonte_cmp || ' ' || data_cmp || ' (' || ordem_cmp || ')' AS comparado,
       classificacao, severity,
       json_extract(detalhe, '$.linhas_divergentes') AS linhas_divergentes,
       json_extract(detalhe, '$.linhas_exclusivas_cmp') AS linhas_novas
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 2 AND cd_conta IS NULL
ORDER BY periodo_fim DESC, data_cmp;

-- Linhas: o que mudou na DRE anual de <ANO> entre o DFP original e o DFP seguinte
SELECT cd_conta, ds_conta, valor_ref AS original, valor_cmp AS reapresentado,
       diff_abs, ROUND(diff_rel * 100, 2) AS diff_pct, classificacao
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 2 AND tipo_doc = 'DRE'
  AND periodo_fim = '<ANO>-12-31' AND fonte_cmp = 'DFP' AND cd_conta IS NOT NULL
ORDER BY cd_conta;
```
Se a empresa não tiver linhas em `consistency_flags`, a Camada 2 ainda não rodou para ela — informar o
comando `run_all.py --layer 2 --cnpj <CNPJ>`. Ausência de flags para um período com filings pareados
significa que os valores bateram dentro da tolerância.

```

- [ ] **Step 3: `CLAUDE.md` — item no "Comportamento esperado ao pesquisar"**

Acrescentar depois do item 6 (financeiros) e renumerar o antigo 7 para 8:

```markdown
7. **Para "esse número foi reapresentado?"**: consulte `consistency_flags` (Camada 2) filtrando por
   `cnpj_companhia`, `tipo_doc` e `periodo_fim`. Apresente sempre o valor original (`valor_ref`) e o
   reapresentado (`valor_cmp`) lado a lado — o padrão do banco é o original, nunca substituir.
```

- [ ] **Step 4: `README.md` — árvore e seção**

Na árvore de "Estrutura do projeto", logo depois do bloco `scripts/ingest/`, acrescentar:

```
│   ├── analysis/                # consistência dos demonstrativos (fora do job semanal)
│   │   ├── consistency_utils.py     # latest_rows, tolerância, consistency_runs/flags
│   │   ├── check_cross_period.py    # Camada 2: cruzamento entre filings (reapresentação)
│   │   └── run_all.py               # orquestrador: --layer 2 --cnpj|--full
```

Antes de `## Histórico`, inserir:

```markdown
## Análise de consistência dos demonstrativos

Scripts em `scripts/analysis/` cruzam os quadros de `demonstrativos_contabeis` e gravam achados em
`consistency_runs` / `consistency_flags` (metadados; o valor publicado pela CVM nunca é alterado).
Não entram no job semanal — rodar à mão depois de reingerir DFP/ITR:

```bash
cd scripts/analysis && source ../../.venv/bin/activate
python run_all.py --layer 2 --cnpj 84.429.695/0001-11   # uma empresa
python run_all.py --layer 2 --full                       # base inteira (~145 empresas, poucos minutos)
```

| Camada | Script | O que detecta |
|---|---|---|
| 2 | `check_cross_period.py` | O mesmo período em filings diferentes (DFP × ITRs seguintes × DFP seguinte): `reapresentacao` quando o total diverge, `reclassificacao` quando só sublinhas mudam. Baseline = filing mais antigo. |

Plano e camadas seguintes: `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md`.

```

A seção `## Testes` só tem o comando `pytest` — deixar como está.

- [ ] **Step 5: `scripts/mcp/cvm_mcp.py` — docstring de `query`**

Na docstring de `query` (linhas 73–80), na lista de tabelas, acrescentar `consistency_runs, consistency_flags` depois de `notas_explicativas`, e uma linha:

```
    consistency_flags: achados de consistência (layer=2 cross_period: reapresentacao/reclassificacao entre filings;
    cd_conta NULL = resumo do par; detalhe é JSON — use json_extract).
```

- [ ] **Step 6: Ponteiro no plano-mãe**

Em `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md`, logo abaixo do título `## Fase 1 — Tabelas de achados + Camada 2 (cruzamento entre filings)`, inserir:

```markdown
> **Plano de tarefas (executado):** `docs/superpowers/plans/2026-09-17-fase1-camada2-cross-period.md`.
```

- [ ] **Step 7: Conferir que o MCP ainda sobe e vê a tabela**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -c "import ast,sys; ast.parse(open('scripts/mcp/cvm_mcp.py').read()); print('ok')" && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: `ok` e suíte PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add CLAUDE.md README.md scripts/mcp/cvm_mcp.py docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md && git commit -m "docs: consistency_flags (Camada 2) no CLAUDE.md, README e docstring do MCP

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Verificação geral da Fase 1

- `pytest tests/` passa sem tocar `cvm_research.db` (todos os testes usam `:memory:` + `schema.sql`).
- `schema.sql` aplicado em banco vazio e no real sem erro (Task 1).
- Caso âncora WEGE3 = 0 flags (Task 5); números de verificação na ordem de grandeza do plano-mãe (Task 6).
- `SELECT layer, classificacao, severity, COUNT(*) FROM consistency_flags GROUP BY 1,2,3` via MCP responde só `layer = 2` com as duas classes.
- Pronto para a Fase 2 (Camada 1 usa `latest_rows`, `tolerancia`, `new_run`/`write_flags`/`clear_flags` sem mudanças; `run_all.LAYERS` ganha a chave `1`).
