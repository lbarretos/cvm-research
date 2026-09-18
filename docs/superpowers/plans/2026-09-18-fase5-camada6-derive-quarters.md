# Fase 5 — Camada 6 (desacúmulo) + `demonstrativos_trimestrais` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Expande a seção "Fase 5" do plano-mãe `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` em tarefas com código, seguindo o precedente das Fases 1–4. Pré-requisito: Fase 4 mesclada em `main` (confirmado em 2026-09-18, merge do PR #15, commit `e24b23d`); Camada 2 executada (a Camada 6 lê os resumos `reapresentacao` dela).

**Goal:** Criar a tabela `demonstrativos_trimestrais` e a Camada 6, que produz o valor de cada trimestre da DRE, DFC_MI e DVA por conta e por safra (`original` = colunas `Último`; `reapresentado` = colunas `Penúltimo` dos filings do exercício seguinte), usando a linha trimestral publicada quando existe (DRE 1T–3T) e derivando o resto por diferença de acumulados da **mesma safra** (`acum(Qn) − acum(Qn−1)`; 4T = `DFP − acum(3T)`), com flags para publicado ≠ derivado, componente reapresentado, linha sem par e buracos na série.

**Architecture:** `derive_quarters.py` lê `latest_rows` por empresa, separa as safras pela `ordem_exercicio`, identifica em cada documento o período acumulado (menor `dt_ini_exerc`) e o trimestre pela duração (`meses/3`, o que já resolve exercício social fora do calendário), monta os exercícios `(exercicio_ini → {n: documento})` e deriva linha a linha (`derive_quarters` → `_derivar_exercicio`). Grava em `demonstrativos_trimestrais` (uma linha por conta × trimestre × safra) e em `consistency_flags` (`layer = 6`) as flags de linha `reapresentacao_intra_ano` e as flags-resumo por trimestre (`componente_reapresentado`, `sem_anterior`, `sem_3t`, `sem_dfp`). Mesmo CLI, idempotência por `(cnpj[, tipo_doc])` nas duas tabelas, passo `consistency_l6` no `update_weekly.sh`.

**Tech Stack:** Python 3.14 (`.venv`), `pandas` 2.2, `sqlite3` 3.50, `pytest` 8.3.

---

## Decisões de desenho verificadas contra o banco (2026-09-18, protótipo no scratchpad, base inteira, 49 s)

| Ponto | O que a base mostra | Decisão |
|---|---|---|
| Publicado na safra reapresentada | O `Penúltimo` do ITR 2T/3T tem a linha trimestral isolada da DRE (WEG ITR 2T24 Penúltimo: `3.01` acum 15.867 mi + 2T23 isolado 8.171 mi). | As duas safras têm `vl_publicado` na DRE 1T–3T; a regra de safra vale igual. |
| Trimestre | Duração do acumulado (`meses(dt_ini, dt_fim)`) é 3/6/9/12 em quase todos os docs; ~40 docs têm 1, 2, 5, 8 ou 13 meses, DFP com 3/6/9 meses ou ITR com 12 (mudança de exercício, primeiro exercício). | `trimestre = meses/3`; doc irregular (duração fora de {3,6,9,12} ou `DFP` ⇔ `n = 4` violado) não entra e conta em `stats.docs_irregulares`. Exercício começando em abril: 04-01 → 06-30 = 3 meses = 1T. |
| Buracos | 4T sem 3T: ≈ 165 exercícios por tipo/safra (primeiros anos: DFP desde 2010, ITR desde 2011); 3T sem DFP: 5–14; 2T sem 1T / 3T sem 2T: 6–9. | Sem acumulado anterior → linha gravada com `vl_derivado` NULL e flag `sem_3t` (n = 4) ou `sem_anterior` (n = 2, 3; classe nova); na DRE `vl_final` = publicado. Sem DFP → não há linha de 4T; flag-resumo `sem_dfp` só em `consistency_flags`. |
| Linhas sem par | Entre `DFP(Y)` e `ITR 3T(Y)` acumulado há código exclusivo em 1.903 de 3.317 pares da DRE e em **3.142 de 3.286** da DFC (23 mil linhas). Derivar com o lado ausente = 0 atribuiria o valor do ano inteiro ao 4T. | Código ausente no acumulado anterior → `vl_derivado` NULL, flag `linha_sem_par` (classe nova; na DRE 1T–3T `vl_final` = publicado). Código ausente no acumulado atual → sem linha (não há o que derivar; a Camada 3 explica). Só em `consistency_flags` não entra (a Camada 3 já cobre). |
| Lucro por ação | `3.99*` aparece como "divergência" (BB 2T23: publicado 5.860 vs derivado 10.540): LPA não é aditivo entre trimestres. | `3.99` e descendentes ficam fora da derivação (mesma exceção da Camada 1). |
| Publicado × derivado na DRE | 13.626 de 245.664 linhas (5,5%) divergem acima da tolerância, incluindo `3.99`; 60 linhas de acumulado sem linha trimestral publicada. | `reapresentacao_intra_ano` por linha (`warn`), gravada também em `consistency_flags`; sem publicado → `origem = 'derivado'`. Números por documento medidos na Task 5. |
| Checagem do 4T da DFC | O BPA `Penúltimo` do ITR 3T(Y+1) é o balanço de 31/12/Y, não de 30/09/Y: a variação de caixa pelo BPA só existe na safra original (1.629 checados, 163 divergentes, 1.657 sem BPA). A própria DFC tem `6.05.02` (saldo final) em 99,8% dos docs. | Referência principal: `6.05.02(DFP) − 6.05.02(3T)` (vale nas duas safras); reserva: BPA `1.01.01` (31/12 − 30/09, só original). `|6.05 derivado − referência| > tol` → `reapresentacao_intra_ano` na linha `6.05` do 4T, com `detalhe.verificacao`. |
| Componente reapresentado | A Camada 2 tem 1.150 resumos `reapresentacao` na DRE, 293 na DFC, 791 na DVA. | Conjunto `(tipo_doc, fonte, data_referencia, ordem, periodo_ini, periodo_fim)` dos dois lados desses resumos; trimestre cujo minuendo ou subtraendo está no conjunto → `componente_reapresentado` (info), em qualquer trimestre derivado, não só no 4T. Precedência por linha: `reapresentacao_intra_ano` > `linha_sem_par`/`sem_anterior`/`sem_3t` > `componente_reapresentado`. |
| Caso âncora | WEGE3 2024 `3.01`: 1T 8.033 mi, 2T 9.274 mi, 3T 9.857 mi publicados; acum 3T 27.165 mi; DFP 37.987 mi → 4T derivado 10.822 mi. | Teste de fumaça da Task 4. |
| Rastreabilidade | Como nas Fases 1 e 4. | Colunas extras `run_id` (FK) e `exercicio_ini`; CHECK de `flag` com `linha_sem_par` e `sem_anterior`. |

## Estrutura de arquivos

- **Modify:** `schema.sql` — `demonstrativos_trimestrais` + índice, depois de `idx_timeline_class`.
- **Create:** `scripts/analysis/derive_quarters.py` — `meses`, `trimestre_de`, `inicio_trimestre`, `docs_acumulados`, `_derivar_exercicio`, `derive_quarters`, `reapresentados_camada2`, `clear_trimestrais`, `write_trimestrais`, `main`.
- **Modify:** `scripts/analysis/run_all.py` (camada 6), `scripts/update_weekly.sh` (`consistency_l6`).
- **Create:** `tests/test_derive_quarters.py`.
- **Modify:** `CLAUDE.md`, `README.md`, `scripts/mcp/cvm_mcp.py`, plano-mãe.

---

### Task 0: Branch — `git checkout -b fase-5-camada-6` a partir de `main` limpo.

### Task 1: Schema + funções de calendário

- [x] **Step 1: Testes que falham** — criar `tests/test_derive_quarters.py`:

```python
"""
Fase 5 da consistência financeira: Camada 6 (desacúmulo) + demonstrativos_trimestrais.
"""
import os
import sqlite3
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import derive_quarters as dq

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def test_schema_trimestrais():
    conn = _db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(demonstrativos_trimestrais)")]
    assert {"run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
            "cd_conta", "ds_conta", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
            "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"} <= set(cols)
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('r', 6, 'derive_quarters')")
    sql = ("INSERT INTO demonstrativos_trimestrais (run_id, cnpj_companhia, tipo_doc, safra, exercicio_ini, dt_ini_exerc, "
           "dt_fim_exerc, trimestre, cd_conta, origem, flag) VALUES ('r', ?, 'DRE', 'original', '2024-01-01', ?, ?, ?, '3.01', 'derivado', ?)")
    conn.execute(sql, (CNPJ, "2024-10-01", "2024-12-31", 4, "linha_sem_par"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2024-10-01", "2024-12-31", 4, None))          # UNIQUE (cnpj, tipo, safra, fim, conta)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2025-01-01", "2025-03-31", 5, None))          # trimestre 1..4
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (CNPJ, "2025-01-01", "2025-03-31", 1, "inventada"))   # CHECK flag


def test_calendario():
    assert dq.meses("2024-01-01", "2024-03-31") == 3 and dq.meses("2024-01-01", "2024-12-31") == 12
    assert dq.meses("2023-04-01", "2024-03-31") == 12 and dq.meses("2024-01-01", "2024-01-31") == 1
    assert dq.trimestre_de("2024-01-01", "2024-06-30") == 2 and dq.trimestre_de("2023-04-01", "2023-06-30") == 1
    assert dq.trimestre_de("2024-01-01", "2024-01-31") is None and dq.trimestre_de("2023-01-01", "2024-01-31") is None
    assert dq.inicio_trimestre("2024-01-01", 1) == "2024-01-01" and dq.inicio_trimestre("2024-01-01", 4) == "2024-10-01"
    assert dq.inicio_trimestre("2023-04-01", 4) == "2024-01-01"
```

- [x] **Step 2: Rodar e ver falhar** (`ModuleNotFoundError: derive_quarters`).
- [x] **Step 3: Implementar** — `schema.sql`, depois de `CREATE INDEX IF NOT EXISTS idx_timeline_class ...;`:

```sql

-- Camada 6 (Fase 5): valor de cada trimestre da DRE/DFC_MI/DVA por conta e por
-- safra. 'original' = colunas Último; 'reapresentado' = colunas Penúltimo dos
-- filings do exercício seguinte. Os dois operandos de um derivado vêm sempre da
-- mesma safra. Derivado nunca sobrescreve publicado: vl_final = publicado
-- (DRE 1T–3T) ou derivado (4T, DFC_MI, DVA), conforme `origem`.
CREATE TABLE IF NOT EXISTS demonstrativos_trimestrais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES consistency_runs(run_id),
    cnpj_companhia  TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL CHECK (tipo_doc IN ('DRE','DFC_MI','DVA')),
    safra           TEXT NOT NULL CHECK (safra IN ('original','reapresentado')),
    exercicio_ini   TEXT NOT NULL,        -- início do exercício social (dt_ini_exerc do acumulado)
    dt_ini_exerc    TEXT NOT NULL,        -- início do trimestre
    dt_fim_exerc    TEXT NOT NULL,        -- fim do trimestre
    trimestre       INTEGER NOT NULL CHECK (trimestre BETWEEN 1 AND 4),  -- posição no exercício social
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_publicado    REAL,                 -- linha trimestral do ITR (só DRE 1T–3T)
    vl_derivado     REAL,                 -- acum(Qn) − acum(Qn−1); DFP − acum(3T) no 4T; NULL se não deriva
    origem          TEXT NOT NULL CHECK (origem IN ('publicado','derivado')),
    vl_final        REAL,
    flag            TEXT CHECK (flag IN ('reapresentacao_intra_ano','componente_reapresentado',
                                         'linha_sem_par','sem_anterior','sem_3t','sem_dfp')),
    fonte_a TEXT, data_a TEXT, ordem_a TEXT,   -- filing do minuendo (acumulado do trimestre)
    fonte_b TEXT, data_b TEXT, ordem_b TEXT,   -- filing do subtraendo (NULL no 1T)
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, tipo_doc, safra, dt_fim_exerc, cd_conta)
);
CREATE INDEX IF NOT EXISTS idx_trim_conta ON demonstrativos_trimestrais (cnpj_companhia, tipo_doc, cd_conta, safra, dt_fim_exerc);
```

E `scripts/analysis/derive_quarters.py` (só o calendário nesta task; o resto na Task 2):

```python
"""(docstring completa na Task 2)"""
from datetime import date


def meses(ini: str, fim: str) -> int:
    """Meses cobertos por [ini, fim]: 2024-01-01..2024-03-31 → 3."""
    a, b = date.fromisoformat(ini), date.fromisoformat(fim)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def trimestre_de(ini: str, fim: str):
    """Posição do acumulado no exercício social (1..4) ou None se a duração não é 3/6/9/12 meses."""
    m = meses(ini, fim)
    return m // 3 if m in (3, 6, 9, 12) else None


def inicio_trimestre(exercicio_ini: str, n: int) -> str:
    """Primeiro dia do trimestre n do exercício que começa em exercicio_ini."""
    y, m = int(exercicio_ini[:4]), int(exercicio_ini[5:7]) + 3 * (n - 1)
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"
```

- [x] **Step 4: Rodar e ver passar; aplicar o schema no banco real** (`sqlite3 cvm_research.db < schema.sql`).
- [x] **Step 5: Commit** `feat(analysis): demonstrativos_trimestrais no schema; calendário de trimestres (Fase 5)`.

---

### Task 2: `derive_quarters.py` — lógica pura + CLI

- [x] **Step 1: Testes que falham** — acrescentar a `tests/test_derive_quarters.py`:

```python
# ── lógica pura ──────────────────────────────────────────────────────────────

def _doc(fonte, data_ref, ordem, ini, fim, contas, tipo_doc="DRE", tri=None):
    """Linhas de um documento: acumulado (ini..fim) e, se tri, a linha trimestral isolada (tri_ini..fim)."""
    rows = [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref, "versao": 1,
             "ordem_exercicio": ordem, "periodo_ini": ini, "periodo_fim": fim, "cd_conta": cd, "ds_conta": ds,
             "vl_conta": vl, "st_conta_fixa": "S"} for cd, (ds, vl) in contas.items()]
    if tri:
        tri_ini, tri_contas = tri
        rows += [dict(r, periodo_ini=tri_ini, vl_conta=tri_contas[r["cd_conta"]]) for r in rows if r["cd_conta"] in tri_contas]
    return rows


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


R = lambda v: {"3.01": ("Receita", v), "3.11": ("Lucro", v / 10)}
ANO24 = [
    _doc("ITR", "2024-03-31", "Último", "2024-01-01", "2024-03-31", R(100e6)),
    _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", R(230e6), tri=("2024-04-01", {"3.01": 130e6, "3.11": 13e6})),
    _doc("ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30", R(360e6), tri=("2024-07-01", {"3.01": 130e6, "3.11": 13e6})),
    _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", R(500e6)),
]


def _linhas(rows, cd="3.01"):
    return {r["trimestre"]: r for r in rows if r["cd_conta"] == cd}


def test_dre_publicado_nos_tres_primeiros_e_4t_derivado():
    rows, flags, stats = dq.derive_quarters(_df(*ANO24))
    q = _linhas(rows)
    assert [(n, q[n]["vl_publicado"], q[n]["vl_derivado"], q[n]["origem"], q[n]["vl_final"], q[n]["flag"]) for n in (1, 2, 3, 4)] == [
        (1, 100e6, 100e6, "publicado", 100e6, None),
        (2, 130e6, 130e6, "publicado", 130e6, None),
        (3, 130e6, 130e6, "publicado", 130e6, None),
        (4, None, 140e6, "derivado", 140e6, None),
    ]
    r = q[4]
    assert (r["cnpj_companhia"], r["tipo_doc"], r["safra"], r["exercicio_ini"], r["dt_ini_exerc"], r["dt_fim_exerc"]) == \
        (CNPJ, "DRE", "original", "2024-01-01", "2024-10-01", "2024-12-31")
    assert (r["fonte_a"], r["data_a"], r["ordem_a"], r["fonte_b"], r["data_b"], r["ordem_b"]) == \
        ("DFP", "2024-12-31", "Último", "ITR", "2024-09-30", "Último")
    assert (q[1]["fonte_b"], q[1]["data_b"]) == (None, None) and q[1]["ds_conta"] == "Receita"
    assert q[2]["dt_ini_exerc"] == "2024-04-01" and q[2]["dt_fim_exerc"] == "2024-06-30"
    assert len(rows) == 8 and flags == []
    assert stats["DRE"] == {"exercicios": 1, "trimestres": 4, "linhas": 8, "docs_irregulares": 0,
                            "reapresentacao_intra_ano": 0, "componente_reapresentado": 0, "linha_sem_par": 0,
                            "sem_anterior": 0, "sem_3t": 0, "sem_dfp": 0}


def test_publicado_diferente_do_derivado_gera_flag_e_mantem_publicado():
    docs = [d.copy() for d in ANO24]
    docs[1] = _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", R(230e6), tri=("2024-04-01", {"3.01": 125e6, "3.11": 13e6}))
    rows, flags, stats = dq.derive_quarters(_df(*docs))
    r = _linhas(rows)[2]
    assert (r["vl_publicado"], r["vl_derivado"], r["vl_final"], r["flag"]) == (125e6, 130e6, 125e6, "reapresentacao_intra_ano")
    f, = flags
    assert (f["layer"], f["check_type"], f["classificacao"], f["severity"], f["cd_conta"], f["tipo_doc"]) == \
        (6, "derive_quarters", "reapresentacao_intra_ano", "warn", "3.01", "DRE")
    assert (f["periodo_ini"], f["periodo_fim"], f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == ("2024-04-01", "2024-06-30", 125e6, 130e6, 5e6)
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("ITR", "2024-06-30", "ITR", "2024-03-31")
    assert f["detalhe"] == {"safra": "original", "trimestre": 2, "exercicio_ini": "2024-01-01"}
    assert stats["DRE"]["reapresentacao_intra_ano"] == 1


def test_dfc_so_derivado_e_checagem_de_caixa_no_4t():
    D = lambda op, ini, fim: {"6.01": ("Operacional", op), "6.05": ("Variação de caixa", fim - ini),
                              "6.05.01": ("Saldo inicial", ini), "6.05.02": ("Saldo final", fim)}
    docs = [_doc("ITR", "2024-03-31", "Último", "2024-01-01", "2024-03-31", D(10e6, 50e6, 60e6), "DFC_MI"),
            _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", D(25e6, 50e6, 75e6), "DFC_MI"),
            _doc("ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30", D(40e6, 50e6, 90e6), "DFC_MI"),
            _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", D(60e6, 50e6, 110e6), "DFC_MI")]
    rows, flags, _ = dq.derive_quarters(_df(*docs))
    q = _linhas(rows, "6.01")
    assert [(q[n]["vl_publicado"], q[n]["vl_derivado"], q[n]["origem"], q[n]["vl_final"]) for n in (1, 2, 3, 4)] == \
        [(None, 10e6, "derivado", 10e6), (None, 15e6, "derivado", 15e6), (None, 15e6, "derivado", 15e6), (None, 20e6, "derivado", 20e6)]
    assert _linhas(rows, "6.05")[4]["flag"] is None and flags == []
    docs[3] = _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", D(60e6, 45e6, 110e6), "DFC_MI")   # saldo inicial reapresentado
    rows, flags, _ = dq.derive_quarters(_df(*docs))
    r = _linhas(rows, "6.05")[4]
    assert (r["vl_derivado"], r["flag"]) == (25e6, "reapresentacao_intra_ano")       # 65 − 40 = 25 ≠ 110 − 90 = 20
    f, = flags
    assert (f["cd_conta"], f["valor_ref"], f["valor_cmp"]) == ("6.05", 25e6, 20e6) and f["detalhe"]["verificacao"] == "saldo_final"


def test_dfc_4t_usa_bpa_quando_nao_ha_saldo_final_so_na_safra_original():
    D = lambda op: {"6.01": ("Operacional", op), "6.05": ("Variação de caixa", op)}
    B = lambda cx, fim, ordem="Último", data=None: [{"cnpj_companhia": CNPJ, "fonte": "DFP" if fim.endswith("12-31") else "ITR",
        "tipo_doc": "BPA", "data_referencia": data or fim, "versao": 1, "ordem_exercicio": ordem, "periodo_ini": "NA", "periodo_fim": fim,
        "cd_conta": "1.01.01", "ds_conta": "Caixa", "vl_conta": cx, "st_conta_fixa": "S"}]
    docs = [_doc("ITR", "2024-03-31", "Último", "2024-01-01", "2024-03-31", D(10e6), "DFC_MI"),
            _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", D(25e6), "DFC_MI"),
            _doc("ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30", D(40e6), "DFC_MI"),
            _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31", D(60e6), "DFC_MI")]
    rows, flags, _ = dq.derive_quarters(_df(*docs, B(90e6, "2024-09-30"), B(110e6, "2024-12-31")))
    assert _linhas(rows, "6.05")[4]["flag"] is None                                  # 20 = 110 − 90
    rows, flags, _ = dq.derive_quarters(_df(*docs, B(90e6, "2024-09-30"), B(115e6, "2024-12-31")))
    assert _linhas(rows, "6.05")[4]["flag"] == "reapresentacao_intra_ano" and flags[0]["detalhe"]["verificacao"] == "bpa_caixa"
    rows, flags, _ = dq.derive_quarters(_df(*docs))                                 # sem BPA: sem checagem
    assert _linhas(rows, "6.05")[4]["flag"] is None and flags == []


def test_safra_reapresentada_usa_so_penultimo():
    pen = [_doc("ITR", "2025-03-31", "Penúltimo", "2024-01-01", "2024-03-31", R(101e6)),
           _doc("ITR", "2025-06-30", "Penúltimo", "2024-01-01", "2024-06-30", R(231e6), tri=("2024-04-01", {"3.01": 130e6, "3.11": 13e6})),
           _doc("ITR", "2025-09-30", "Penúltimo", "2024-01-01", "2024-09-30", R(361e6), tri=("2024-07-01", {"3.01": 130e6, "3.11": 13e6})),
           _doc("DFP", "2025-12-31", "Penúltimo", "2024-01-01", "2024-12-31", R(510e6))]
    rows, _, stats = dq.derive_quarters(_df(*ANO24, *pen))
    orig = {r["trimestre"]: r for r in rows if r["cd_conta"] == "3.01" and r["safra"] == "original"}
    reap = {r["trimestre"]: r for r in rows if r["cd_conta"] == "3.01" and r["safra"] == "reapresentado"}
    assert (orig[4]["vl_derivado"], reap[4]["vl_derivado"]) == (140e6, 149e6)          # nunca mistura safras
    assert (reap[1]["vl_final"], reap[2]["vl_final"], reap[2]["vl_derivado"]) == (101e6, 130e6, 130e6)
    assert (reap[4]["fonte_a"], reap[4]["data_a"], reap[4]["ordem_a"], reap[4]["data_b"], reap[4]["ordem_b"]) == \
        ("DFP", "2025-12-31", "Penúltimo", "2025-09-30", "Penúltimo")
    assert stats["DRE"]["exercicios"] == 2 and stats["DRE"]["trimestres"] == 8


def test_exercicio_social_comecando_em_abril():
    docs = [_doc("ITR", "2023-06-30", "Último", "2023-04-01", "2023-06-30", R(100e6)),
            _doc("ITR", "2023-09-30", "Último", "2023-04-01", "2023-09-30", R(230e6), tri=("2023-07-01", {"3.01": 130e6, "3.11": 13e6})),
            _doc("ITR", "2023-12-31", "Último", "2023-04-01", "2023-12-31", R(360e6), tri=("2023-10-01", {"3.01": 130e6, "3.11": 13e6})),
            _doc("DFP", "2024-03-31", "Último", "2023-04-01", "2024-03-31", R(500e6))]
    rows, _, _ = dq.derive_quarters(_df(*docs))
    q = _linhas(rows)
    assert [(n, q[n]["dt_ini_exerc"], q[n]["dt_fim_exerc"]) for n in (1, 2, 3, 4)] == [
        (1, "2023-04-01", "2023-06-30"), (2, "2023-07-01", "2023-09-30"), (3, "2023-10-01", "2023-12-31"), (4, "2024-01-01", "2024-03-31")]
    assert q[4]["vl_derivado"] == 140e6 and {r["exercicio_ini"] for r in rows} == {"2023-04-01"}


def test_linha_sem_par_e_lucro_por_acao_ignorado():
    docs = [d.copy() for d in ANO24]
    docs[3] = _doc("DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31",
                   dict(R(500e6), **{"3.04": ("Despesas", -50e6), "3.99": ("LPA", 1.2), "3.99.01": ("Básico", 1.2)}))
    rows, flags, stats = dq.derive_quarters(_df(*docs))
    r = [x for x in rows if x["cd_conta"] == "3.04"][0]
    assert (r["trimestre"], r["vl_derivado"], r["vl_final"], r["origem"], r["flag"]) == (4, None, None, "derivado", "linha_sem_par")
    assert not [x for x in rows if x["cd_conta"].startswith("3.99")]
    assert flags == [] and stats["DRE"]["linha_sem_par"] == 1


def test_buracos_sem_anterior_sem_3t_sem_dfp():
    docs = [ANO24[0], ANO24[2], ANO24[3]]                                          # sem 2T
    rows, flags, stats = dq.derive_quarters(_df(*docs))
    q = _linhas(rows)
    assert (q[3]["vl_publicado"], q[3]["vl_derivado"], q[3]["vl_final"], q[3]["flag"]) == (130e6, None, 130e6, "sem_anterior")
    assert q[4]["vl_derivado"] == 140e6 and q[4]["flag"] is None
    f, = flags
    assert (f["classificacao"], f["severity"], f["cd_conta"], f["periodo_ini"], f["periodo_fim"]) == ("sem_anterior", "info", None, "2024-07-01", "2024-09-30")
    assert f["detalhe"] == {"safra": "original", "trimestre": 3, "exercicio_ini": "2024-01-01", "linhas": 2}
    rows, flags, stats = dq.derive_quarters(_df(ANO24[0], ANO24[1], ANO24[3]))     # sem 3T
    q = _linhas(rows)
    assert (q[4]["vl_derivado"], q[4]["vl_final"], q[4]["flag"]) == (None, None, "sem_3t") and flags[0]["classificacao"] == "sem_3t"
    rows, flags, stats = dq.derive_quarters(_df(*ANO24[:3]))                        # sem DFP
    assert 4 not in _linhas(rows) and [f["classificacao"] for f in flags] == ["sem_dfp"]
    assert (flags[0]["periodo_ini"], flags[0]["periodo_fim"], flags[0]["cd_conta"]) == ("2024-01-01", "2024-09-30", None)
    assert stats["DRE"]["sem_dfp"] == 1


def test_componente_reapresentado_pela_camada2():
    reap = {("DRE", "DFP", "2024-12-31", "Último", "2024-01-01", "2024-12-31")}
    rows, flags, stats = dq.derive_quarters(_df(*ANO24), reapresentados=reap)
    q = _linhas(rows)
    assert q[4]["flag"] == "componente_reapresentado" and q[3]["flag"] is None
    f, = flags
    assert (f["classificacao"], f["severity"], f["cd_conta"], f["detalhe"]["linhas"]) == ("componente_reapresentado", "info", None, 2)
    assert stats["DRE"]["componente_reapresentado"] == 2


def test_documento_irregular_e_dataframe_vazio():
    docs = [*ANO24, _doc("ITR", "2025-01-31", "Último", "2025-01-01", "2025-01-31", R(30e6)),
            _doc("DFP", "2025-06-30", "Último", "2025-01-01", "2025-06-30", R(200e6))]
    rows, _, stats = dq.derive_quarters(_df(*docs))
    assert {r["exercicio_ini"] for r in rows} == {"2024-01-01"} and stats["DRE"]["docs_irregulares"] == 2
    assert dq.derive_quarters(pd.DataFrame()) == ([], [], {})


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

def _db_com_docs():
    conn = _db()
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    docs = [d.copy() for d in ANO24]
    docs[1] = _doc("ITR", "2024-06-30", "Último", "2024-01-01", "2024-06-30", R(230e6), tri=("2024-04-01", {"3.01": 125e6, "3.11": 13e6}))
    rows = [r for d in docs for r in d]
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r["periodo_ini"] if c == "dt_ini_exerc" else r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols) for r in rows])
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('l2', 2, 'cross_period')")
    conn.execute("""INSERT INTO consistency_flags (run_id, layer, check_type, classificacao, severity, cnpj_companhia, tipo_doc,
        periodo_ini, periodo_fim, fonte_ref, data_ref, ordem_ref, fonte_cmp, data_cmp, ordem_cmp)
        VALUES ('l2', 2, 'cross_period', 'reapresentacao', 'warn', ?, 'DRE', '2024-01-01', '2024-09-30',
        'ITR', '2024-09-30', 'Último', 'ITR', '2025-09-30', 'Penúltimo')""", (CNPJ,))
    conn.commit()
    return conn


def test_reapresentados_camada2_le_os_dois_lados():
    conn = _db_com_docs()
    assert dq.reapresentados_camada2(conn, CNPJ) == {("DRE", "ITR", "2024-09-30", "Último", "2024-01-01", "2024-09-30"),
                                                     ("DRE", "ITR", "2025-09-30", "Penúltimo", "2024-01-01", "2024-09-30")}


def test_main_grava_trimestrais_flags_e_substitui(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(dq, "get_db", lambda: conn)
    run1 = dq.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT trimestre, cd_conta, origem, vl_final, flag FROM demonstrativos_trimestrais WHERE run_id = ? ORDER BY trimestre, cd_conta", (run1,)).fetchall()
    assert got == [(1, "3.01", "publicado", 100e6, None), (1, "3.11", "publicado", 10e6, None),
                   (2, "3.01", "publicado", 125e6, "reapresentacao_intra_ano"), (2, "3.11", "publicado", 13e6, None),
                   (3, "3.01", "publicado", 130e6, "componente_reapresentado"), (3, "3.11", "publicado", 13e6, "componente_reapresentado"),
                   (4, "3.01", "derivado", 140e6, "componente_reapresentado"), (4, "3.11", "derivado", 14e6, "componente_reapresentado")]
    assert conn.execute("SELECT classificacao, COUNT(*) FROM consistency_flags WHERE layer = 6 GROUP BY 1 ORDER BY 1").fetchall() == \
        [("componente_reapresentado", 2), ("reapresentacao_intra_ano", 1)]
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run == (6, "derive_quarters", f"cnpj={CNPJ}", 4, 8)                     # 4 trimestres; 8 linhas
    run2 = dq.main(["--cnpj", CNPJ, "--tipo-doc", "DRE"])
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM demonstrativos_trimestrais").fetchone() == (8, 1)
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags WHERE layer = 6").fetchone() == (3, 1)
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags WHERE layer = 2").fetchone()[0] == 1
    out = capsys.readouterr().out
    assert "DRE" in out and "trimestres=4" in out and "reapresentacao_intra_ano=1" in out


def test_main_full_e_exigencia_de_cnpj(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(dq, "get_db", lambda: conn)
    run_id = dq.main(["--full"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    with pytest.raises(SystemExit):
        dq.main([])
```

- [x] **Step 2: Rodar e ver falhar** (`AttributeError: derive_quarters` etc.).
- [x] **Step 3: Completar `scripts/analysis/derive_quarters.py`**

```python
"""
Camada 6 — desacúmulo (check_type = 'derive_quarters') → demonstrativos_trimestrais.

Para cada (cnpj, tipo_doc ∈ {DRE, DFC_MI, DVA}, safra):
  - safra 'original'      = colunas ordem_exercicio = 'Último' de cada filing;
  - safra 'reapresentado' = colunas 'Penúltimo' dos filings do exercício seguinte.
Os dois operandos de um derivado vêm SEMPRE da mesma safra.

Em cada documento, o acumulado é a linha com menor dt_ini_exerc; o trimestre é a
duração do acumulado (3/6/9/12 meses → 1..4), o que também resolve exercício
social fora do calendário. Documento com outra duração (ou DFP que não é o 4T)
é irregular e não entra. Por exercício (exercicio_ini) e trimestre n:
  - vl_publicado : DRE 1T–3T, linha trimestral isolada do ITR (dt_ini = início do trimestre)
  - vl_derivado  : n = 1 → acum(1T); n > 1 → acum(Qn) − acum(Qn−1); n = 4 → DFP − acum(3T)
  - vl_final     : publicado quando existe (origem 'publicado'), senão derivado
Flags (uma por linha; precedência nesta ordem):
  - 'reapresentacao_intra_ano' (warn): |publicado − derivado| > tolerância; na DFC,
    6.05 derivado do 4T ≠ variação do saldo final (6.05.02 DFP − 6.05.02 3T; reserva:
    BPA 1.01.01 na safra original) — também vira flag de linha em consistency_flags
  - 'linha_sem_par' (info): conta ausente do acumulado anterior (não deriva)
  - 'sem_anterior' / 'sem_3t' (info): não há acumulado anterior (2T/3T; 4T)
  - 'componente_reapresentado' (info): minuendo ou subtraendo aparece num resumo
    'reapresentacao' da Camada 2 (consistency_flags layer 2)
  - 'sem_dfp': 3T sem DFP — só flag-resumo em consistency_flags (não há linha de 4T)
3.99 (lucro por ação) e descendentes ficam fora: LPA não é aditivo.
Flags-resumo por trimestre (cd_conta NULL) em consistency_flags para
componente_reapresentado / sem_anterior / sem_3t / sem_dfp. Linhas anteriores do
mesmo (cnpj[, tipo_doc]) são apagadas nas duas tabelas antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) depois da Camada 5. À mão
(na pasta scripts/analysis, .venv ativo):
  python derive_quarters.py --cnpj 84.429.695/0001-11
  python derive_quarters.py --cnpj 84.429.695/0001-11 --tipo-doc DRE --desde 2020
  python derive_quarters.py --full               # base inteira (~145 empresas)
"""
from datetime import date

import pandas as pd

from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows, new_run,
                               parent_code, tolerancia, write_flags)

LAYER = 6
CHECK_TYPE = "derive_quarters"
TIPOS = ["DRE", "DFC_MI", "DVA"]
SAFRAS = {"original": "Último", "reapresentado": "Penúltimo"}
SEVERITY = {"reapresentacao_intra_ano": "warn", "componente_reapresentado": "info", "linha_sem_par": "info",
            "sem_anterior": "info", "sem_3t": "info", "sem_dfp": "info"}
SKIP_PREFIX = "3.99"
COLS = ["run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
        "cd_conta", "ds_conta", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
        "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"]


# ── calendário ───────────────────────────────────────────────────────────────

def meses(ini: str, fim: str) -> int:
    """Meses cobertos por [ini, fim]: 2024-01-01..2024-03-31 → 3."""
    a, b = date.fromisoformat(ini), date.fromisoformat(fim)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def trimestre_de(ini: str, fim: str):
    """Posição do acumulado no exercício social (1..4) ou None se a duração não é 3/6/9/12 meses."""
    m = meses(ini, fim)
    return m // 3 if m in (3, 6, 9, 12) else None


def inicio_trimestre(exercicio_ini: str, n: int) -> str:
    """Primeiro dia do trimestre n do exercício que começa em exercicio_ini."""
    y, m = int(exercicio_ini[:4]), int(exercicio_ini[5:7]) + 3 * (n - 1)
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


# ── leitura dos documentos ───────────────────────────────────────────────────

def _valor(v):
    return 0.0 if v is None or pd.isna(v) else float(v)


def _texto(v):
    return v if isinstance(v, str) else None


def docs_acumulados(dd: pd.DataFrame) -> tuple[dict, int]:
    """dd = linhas de um (tipo_doc, ordem_exercicio). Retorna ({(exercicio_ini, n): doc}, irregulares).
    doc = {"fonte", "data", "ordem", "ini", "fim", "acum": {cd: (ds, vl)}, "tri": {cd: vl}} — tri só
    tem as linhas de período curto (dt_ini > exercicio_ini), i.e. o trimestre isolado da DRE."""
    docs: dict = {}
    irregulares = 0
    for (fonte, data_ref, ordem), g in dd.groupby(["fonte", "data_referencia", "ordem_exercicio"], sort=True):
        g = g[g["periodo_ini"] != "NA"]
        if g.empty:
            continue
        ini, fim = g["periodo_ini"].min(), g["periodo_fim"].iloc[0]
        n = trimestre_de(ini, fim)
        if n is None or (fonte == "DFP") != (n == 4):
            irregulares += 1
            continue
        acum = {}
        tri = {}
        for r in g.itertuples(index=False):
            if r.cd_conta.startswith(SKIP_PREFIX):
                continue
            if r.periodo_ini == ini:
                acum.setdefault(r.cd_conta, (_texto(r.ds_conta), r.vl_conta))
            else:
                tri.setdefault(r.cd_conta, r.vl_conta)
        docs[(ini, n)] = {"fonte": fonte, "data": data_ref, "ordem": ordem, "ini": ini, "fim": fim, "acum": acum, "tri": tri}
    return docs, irregulares


def _chave(tipo_doc: str, doc: dict) -> tuple:
    return (tipo_doc, doc["fonte"], doc["data"], doc["ordem"], doc["ini"], doc["fim"])


def _saldo_caixa(doc: dict, bpa: dict, safra: str):
    """Referência de caixa no fim do período de `doc`: 6.05.02 da própria DFC ou, na safra
    original, 1.01.01 do BPA com o mesmo dt_fim. Retorna (valor, 'saldo_final'|'bpa_caixa') ou (None, None)."""
    if "6.05.02" in doc["acum"]:
        return _valor(doc["acum"]["6.05.02"][1]), "saldo_final"
    if safra == "original" and doc["fim"] in bpa:
        return bpa[doc["fim"]], "bpa_caixa"
    return None, None


# ── derivação ────────────────────────────────────────────────────────────────

def _derivar_exercicio(cnpj, tipo_doc, safra, exercicio_ini, qs: dict, bpa: dict, reapresentados: set,
                       tol_abs, tol_rel) -> tuple[list[dict], list[dict], dict]:
    """qs = {n: doc} de um exercício. Retorna (linhas, flags, contagens por flag)."""
    rows: list[dict] = []
    flags: list[dict] = []
    cont = {k: 0 for k in SEVERITY}
    for n in sorted(qs):
        a = qs[n]
        b = qs.get(n - 1) if n > 1 else None
        ini_q, fim_q = inicio_trimestre(exercicio_ini, n), a["fim"]
        falta = None if (n == 1 or b is not None) else ("sem_3t" if n == 4 else "sem_anterior")
        componente = _chave(tipo_doc, a) in reapresentados or (b is not None and _chave(tipo_doc, b) in reapresentados)
        docs_ab = {"fonte_a": a["fonte"], "data_a": a["data"], "ordem_a": a["ordem"],
                   "fonte_b": b["fonte"] if b else None, "data_b": b["data"] if b else None, "ordem_b": b["ordem"] if b else None}
        base = {"cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "safra": safra, "exercicio_ini": exercicio_ini,
                "dt_ini_exerc": ini_q, "dt_fim_exerc": fim_q, "trimestre": n, **docs_ab}
        linhas_q: list[dict] = []
        for cd, (ds, va) in a["acum"].items():
            if n == 1:
                pub = _valor(va) if tipo_doc == "DRE" else None
                der = _valor(va)
                flag = None
            else:
                pub = _valor(a["tri"][cd]) if tipo_doc == "DRE" and n < 4 and cd in a["tri"] else None
                if falta:
                    der, flag = None, falta
                elif cd not in b["acum"]:
                    der, flag = None, "linha_sem_par"
                else:
                    der, flag = _valor(va) - _valor(b["acum"][cd][1]), None
            if pub is not None and der is not None and abs(pub - der) > tolerancia(pub, tol_abs, tol_rel):
                flag = "reapresentacao_intra_ano"
                flags.append({
                    "layer": LAYER, "check_type": CHECK_TYPE, "classificacao": flag, "severity": SEVERITY[flag],
                    "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": cd, "cd_conta_pai": parent_code(cd), "ds_conta": ds,
                    "periodo_ini": ini_q, "periodo_fim": fim_q,
                    "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
                    "fonte_cmp": docs_ab["fonte_b"], "data_cmp": docs_ab["data_b"], "ordem_cmp": docs_ab["ordem_b"],
                    "valor_ref": pub, "valor_cmp": der, "diff_abs": der - pub, "diff_rel": (der - pub) / abs(pub) if pub else None,
                    "detalhe": {"safra": safra, "trimestre": n, "exercicio_ini": exercicio_ini},
                })
            elif flag is None and componente:
                flag = "componente_reapresentado"
            linhas_q.append({**base, "cd_conta": cd, "ds_conta": ds, "vl_publicado": pub, "vl_derivado": der,
                             "origem": "publicado" if pub is not None else "derivado",
                             "vl_final": pub if pub is not None else der, "flag": flag})
        # DFC 4T: 6.05 derivado × variação do saldo final de caixa
        if tipo_doc == "DFC_MI" and n == 4 and b is not None:
            linha = next((l for l in linhas_q if l["cd_conta"] == "6.05" and l["vl_derivado"] is not None), None)
            if linha:
                cx_a, modo = _saldo_caixa(a, bpa, safra)
                cx_b, modo_b = _saldo_caixa(b, bpa, safra)
                if cx_a is not None and cx_b is not None and modo == modo_b:
                    ref = cx_a - cx_b
                    if abs(linha["vl_derivado"] - ref) > tolerancia(linha["vl_derivado"], tol_abs, tol_rel):
                        linha["flag"] = "reapresentacao_intra_ano"
                        flags.append({
                            "layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "reapresentacao_intra_ano", "severity": "warn",
                            "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": "6.05", "cd_conta_pai": "6", "ds_conta": linha["ds_conta"],
                            "periodo_ini": ini_q, "periodo_fim": fim_q,
                            "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
                            "fonte_cmp": b["fonte"], "data_cmp": b["data"], "ordem_cmp": b["ordem"],
                            "valor_ref": linha["vl_derivado"], "valor_cmp": ref, "diff_abs": ref - linha["vl_derivado"],
                            "diff_rel": (ref - linha["vl_derivado"]) / abs(linha["vl_derivado"]) if linha["vl_derivado"] else None,
                            "detalhe": {"safra": safra, "trimestre": n, "exercicio_ini": exercicio_ini, "verificacao": modo},
                        })
        for l in linhas_q:
            if l["flag"]:
                cont[l["flag"]] += 1
        # flags-resumo do trimestre
        for classe in ("sem_anterior", "sem_3t", "componente_reapresentado"):
            k = sum(1 for l in linhas_q if l["flag"] == classe)
            if k:
                flags.append({"layer": LAYER, "check_type": CHECK_TYPE, "classificacao": classe, "severity": SEVERITY[classe],
                              "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": None,
                              "periodo_ini": ini_q, "periodo_fim": fim_q,
                              "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
                              "fonte_cmp": docs_ab["fonte_b"], "data_cmp": docs_ab["data_b"], "ordem_cmp": docs_ab["ordem_b"],
                              "detalhe": {"safra": safra, "trimestre": n, "exercicio_ini": exercicio_ini, "linhas": k}})
        rows += linhas_q
    if 3 in qs and 4 not in qs:
        a = qs[3]
        cont["sem_dfp"] += 1
        flags.append({"layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "sem_dfp", "severity": "info",
                      "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": None,
                      "periodo_ini": exercicio_ini, "periodo_fim": a["fim"],
                      "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
                      "detalhe": {"safra": safra, "trimestre": 4, "exercicio_ini": exercicio_ini}})
    return rows, flags, cont


def derive_quarters(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01,
                    reapresentados: set | None = None) -> tuple[list[dict], list[dict], dict]:
    """df = saída de latest_rows (pode incluir BPA, usado só na checagem de caixa).
    Retorna (linhas de demonstrativos_trimestrais, flags, stats[tipo_doc])."""
    rows: list[dict] = []
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return rows, flags, stats
    reapresentados = reapresentados or set()
    for cnpj, dfc in df.groupby("cnpj_companhia", sort=True):
        for tipo_doc in TIPOS:
            d = dfc[dfc["tipo_doc"] == tipo_doc]
            if d.empty:
                continue
            st = stats.setdefault(tipo_doc, {"exercicios": 0, "trimestres": 0, "linhas": 0, "docs_irregulares": 0,
                                             **{k: 0 for k in SEVERITY}})
            for safra, ordem in SAFRAS.items():
                docs, irregulares = docs_acumulados(d[d["ordem_exercicio"] == ordem])
                st["docs_irregulares"] += irregulares
                b = dfc[(dfc["tipo_doc"] == "BPA") & (dfc["ordem_exercicio"] == ordem) & (dfc["cd_conta"] == "1.01.01")]
                bpa = {r.periodo_fim: _valor(r.vl_conta) for r in b.itertuples(index=False)}
                exercicios: dict = {}
                for (ini, n), doc in docs.items():
                    exercicios.setdefault(ini, {})[n] = doc
                for exercicio_ini in sorted(exercicios):
                    qs = exercicios[exercicio_ini]
                    r, f, cont = _derivar_exercicio(cnpj, tipo_doc, safra, exercicio_ini, qs, bpa, reapresentados, tol_abs, tol_rel)
                    st["exercicios"] += 1
                    st["trimestres"] += len(qs)
                    st["linhas"] += len(r)
                    for k, v in cont.items():
                        st[k] += v
                    rows += r
                    flags += f
    return rows, flags, stats


# ── banco ────────────────────────────────────────────────────────────────────

def reapresentados_camada2(conn, cnpj: str) -> set:
    """Documentos (dos dois lados) dos resumos 'reapresentacao' da Camada 2 para a empresa."""
    out = set()
    for r in conn.execute("""SELECT tipo_doc, fonte_ref, data_ref, ordem_ref, fonte_cmp, data_cmp, ordem_cmp, periodo_ini, periodo_fim
                             FROM consistency_flags WHERE layer = 2 AND cd_conta IS NULL AND classificacao = 'reapresentacao'
                               AND cnpj_companhia = ?""", (cnpj,)):
        tipo, fr, dr, orr, fc, dc, oc, pi, pf = r
        out.add((tipo, fr, dr, orr, pi, pf))
        out.add((tipo, fc, dc, oc, pi, pf))
    return out


def clear_trimestrais(conn, cnpj: str, tipo_doc: str | None = None) -> int:
    sql = "DELETE FROM demonstrativos_trimestrais WHERE cnpj_companhia = ?"
    params: list = [cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        params.append(tipo_doc)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def write_trimestrais(conn, run_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = f"INSERT INTO demonstrativos_trimestrais ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})"
    try:
        conn.executemany(sql, [tuple(run_id if c == "run_id" else r.get(c) for c in COLS) for r in rows])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


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
    """Roda a Camada 6 e devolve o run_id. `argv=None` lê sys.argv."""
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
        df = latest_rows(conn, cnpj=cnpj, desde=args.desde, ate=args.ate)
        if args.tipo_doc:
            df = df[df["tipo_doc"].isin([args.tipo_doc, "BPA"])]
        rows, flags, stats = derive_quarters(df, args.tol_abs, args.tol_rel, reapresentados_camada2(conn, cnpj))
        clear_trimestrais(conn, cnpj, args.tipo_doc)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_trimestrais(conn, run_id, rows)
        write_flags(conn, run_id, flags)
        trimestres = sum(s["trimestres"] for s in stats.values())
        total_checked += trimestres
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {trimestres} trimestres, {n} linhas trimestrais, {len(flags)} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (trimestres = exercício × trimestre × safra):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        print(f"  {tipo:7s} exercicios={s['exercicios']} trimestres={s['trimestres']} linhas={s['linhas']} "
              f"irregulares={s['docs_irregulares']} " + " ".join(f"{k}={s[k]}" for k in SEVERITY))
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Rodar e ver passar** (16 testes). **Step 5: Commit** `feat(analysis): Camada 6 — derive_quarters (desacúmulo por safra, flags intra-ano, checagem de caixa)`.

---

### Task 3: `run_all.py` (camada 6) + `update_weekly.sh` (`consistency_l6`, cabeçalho "Camadas 1 a 6"); conferir `--help`, `bash -n`, suíte; commit.

### Task 4: Fumaça WEG — `run_all.py --layer 6 --cnpj 84.429.695/0001-11` duas vezes; conferir 2024 `3.01`: 1T 8.033, 2T 9.274, 3T 9.857 (publicados), 4T 10.822 mi derivado (safra original) e a safra reapresentada; idempotência; flags das outras camadas intactas.

### Task 5: Base inteira — tempo, linhas por tipo/safra/origem, flags por classe, % de documentos ITR (DRE, 2T/3T) com `reapresentacao_intra_ano` (expectativa do plano-mãe: 10–20%), DFC 4T: resultado da checagem de caixa por `verificacao`; registrar no plano-mãe com ponteiro; commit.

### Task 6: Docs — CLAUDE.md (subseção `demonstrativos_trimestrais` + query "série trimestral com 4T derivado" + item 12 de comportamento + defasagem), README (árvore, tabela, camadas), MCP (lista de tabelas + descrição), plano-mãe; commit. Marcar checkboxes; commit.
