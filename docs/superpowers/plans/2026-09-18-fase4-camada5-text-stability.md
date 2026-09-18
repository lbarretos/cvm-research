# Fase 4 — Camada 5 (trilha temporal) + Camada 4 (similaridade) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Expande a seção "Fase 4" do plano-mãe `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` em tarefas com código, seguindo o precedente das Fases 1–3. Pré-requisito: Fase 3 mesclada em `main` (confirmado em 2026-09-18, merge do PR #14, commit `1c1948a`); `normalize_text` já existe em `consistency_utils.py`.

**Goal:** Criar a tabela `cd_conta_ds_timeline` e a Camada 5, que acompanha cada linha (pai + nome) de um demonstrativo entre filings consecutivos da mesma fonte e classifica o que aconteceu com ela: `primeira_ocorrencia`, `estavel` (não gravada), `renumerado` (mesmo nome, código novo), `reformulacao` (nome parecido, score ≥ 0,75), `ambiguo` (0,45 < score < 0,75, fila de revisão), `nova` ou `removida`. A Camada 4 (similaridade textual) é a função `text_similarity` usada no pareamento; não é um script separado.

**Architecture:** `check_text_stability.py` percorre, por `(cnpj, tipo_doc, fonte)`, os filings em ordem de `data_referencia` (`ordem_exercicio = 'Último'`, versão máxima, linhas dedupadas por código) e compara cada filing com o anterior **de cima para baixo na hierarquia**: os pais casados num nível definem quais conjuntos de filhos se comparam no nível seguinte (`compare_filings` → `_comparar_pai`). Grava em `cd_conta_ds_timeline` (uma linha por mudança ou primeira ocorrência) e, para `ambiguo`, também em `consistency_flags` (layer 5, fila de revisão). `consistency_utils.py` ganha `text_similarity` (difflib com token-sort). Mesmo CLI, idempotência por `(cnpj[, tipo_doc])` nas duas tabelas e passo `consistency_l5` no `update_weekly.sh`.

**Tech Stack:** Python 3.14 (`.venv`), `pandas` 2.2, `difflib` (stdlib), `sqlite3` 3.50, `pytest` 8.3.

---

## Decisões de desenho verificadas contra o banco (2026-09-18, protótipo no scratchpad, base inteira, 84 s)

| Ponto | O que a base mostra | Decisão |
|---|---|---|
| Scores de referência | `difflib` sobre texto normalizado: "Obrigações pós emprego" × "Obrigação de benefício pós-emprego" = **0,750**; "Partes relacionadas" × "Fornecedores" = **0,194** (iguais ao plano-mãe). Histograma do melhor par por linha (todos os tipos, 72 mil): bimodal, massas em 0,3–0,4 (18 mil) e 0,8–1,0 (32,5 mil); 0,5–0,7 tem 14,3 mil (20%). | Limiares iniciais do plano-mãe (`≥ 0,75` / `≤ 0,45`), parametrizados (`--sim-alto`, `--sim-baixo`); revisão dos ambíguos na Task 5 decide o corte final. |
| Reordenação de palavras | "Empréstimos e Financiamentos" × "Financiamentos e empréstimos" dá só 0,50 no `difflib` puro. | `text_similarity = max(ratio(a, b), ratio(tokens ordenados))` — token-sort resolve a reordenação sem afetar os demais scores. |
| Volume DFC_MI/DFP | 11.958 mudanças de nome por código (plano-mãe: ≈ 12,8 mil); 961 somem com a normalização (≈ 968); **3.696 renumerações por nome** (≈ 3,6 mil); 3.664 reformulações, 2.264 ambíguas, 3.020 removidas, 5.556 novas. | Números de verificação da Task 5. |
| Colisão de código | **15.151** linhas `removida` cujo código é reutilizado no filing seguinte por outra linha (renumeração em cascata). Com a `UNIQUE (…, data_referencia, cd_conta)` do plano-mãe a gravação falharia. | `UNIQUE (cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta, classificacao)`. `removida` é gravada no filing em que a linha sumiu (`data_referencia` = B) com `cd_conta`/`ds_conta` da linha antiga. |
| Pai renumerado | **1.761** linhas renumeradas têm filhos. Comparar filhos pelo código literal do pai casaria os filhos errados. | `compare_filings` processa os pais por nível (raiz → folhas) e usa o mapa A→B dos pais já casados para escolher o conjunto de filhos de A que corresponde a cada pai de B; código de pai de A que foi para outro lugar não é reutilizado literalmente. |
| Linhas `S` | 5,7 mil sobras `S` em A e 4,7 mil em B (contas padrão omitidas/incluídas); `ds_conta` nunca é NULL. | `S` com o mesmo código dos dois lados → `estavel` mesmo que o nome mude (código fixo pela CVM); `S` casa por nome, mas **nunca entra na similaridade**: sobra `S` vira `nova`/`removida` direto. |
| Rastreabilidade | `consistency_flags` tem `run_id`; a tabela do plano-mãe não. | Colunas extras `run_id` (FK para `consistency_runs`) e `data_referencia_anterior` (filing A da comparação); `cd_conta_pai` nullable (nível 1 não tem pai). |
| `estavel` | ≈ 2 M linhas estáveis por comparação de filings. | Não gravada (como no plano-mãe); a classe fica no `CHECK` só por documentação. `primeira_ocorrencia` é gravada para todas as linhas do primeiro filing de cada `(cnpj, tipo_doc, fonte)`. |

Regras por par de filings consecutivos (A = anterior, B = atual), dentro de cada pai casado:
0. `S` com o mesmo código nos dois lados → `estavel` (sem linha);
1. mesmo `normalize_text(ds_conta)`: mesmo código → `estavel`; código diferente → `renumerado` (`similarity_score = 1.0`, `cd_conta_anterior`);
2. sobras `N` dos dois lados: pareamento guloso por maior `text_similarity`, só pares com score > `sim_baixo`: `≥ sim_alto` → `reformulacao`, senão `ambiguo`;
3. sobras de B → `nova`; sobras de A → `removida`.
Pais de A sem correspondente em B → todos os filhos `removida`; pais de B sem correspondente → filhos comparados com conjunto vazio (todos `nova`).

## Estrutura de arquivos

- **Modify:** `schema.sql` — tabela `cd_conta_ds_timeline` + 2 índices na seção 8 (depois de `idx_cflags_run`).
- **Modify:** `scripts/analysis/consistency_utils.py` — `text_similarity`; `__all__`.
- **Create:** `scripts/analysis/check_text_stability.py` — `_comparar_pai`, `compare_filings`, `check_text_stability`, `write_timeline`, `clear_timeline`, `main`.
- **Modify:** `scripts/analysis/run_all.py` — camada 5; `scripts/update_weekly.sh` — passo `consistency_l5`.
- **Create:** `tests/test_consistency_text.py`.
- **Modify:** `CLAUDE.md` (tabela + query), `README.md`, `scripts/mcp/cvm_mcp.py`, plano-mãe (ponteiro + números + decisão dos cortes).

---

### Task 0: Branch de trabalho

- [x] **Step 1: Criar o branch a partir de `main` limpo**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git status --short && git checkout -b fase-4-camada-5
```

---

### Task 1: Schema + `text_similarity`

**Files:** `schema.sql`, `scripts/analysis/consistency_utils.py`, `tests/test_consistency_text.py` (criar), `tests/test_consistency_utils.py`

- [x] **Step 1: Testes que falham**

Em `tests/test_consistency_utils.py`, logo antes de `# ── latest_rows`:

```python
def test_text_similarity_pares_conhecidos_e_reordenacao():
    assert abs(cu.text_similarity("Obrigações pós emprego", "Obrigação de benefício pós-emprego") - 0.75) < 0.01
    assert abs(cu.text_similarity("Partes relacionadas", "Fornecedores") - 0.19) < 0.01
    assert cu.text_similarity("Empréstimos e Financiamentos", "FINANCIAMENTOS E EMPRÉSTIMOS") == 1.0   # token-sort
    assert cu.text_similarity("Caixa", "Caixa") == 1.0 and cu.text_similarity("", "Caixa") == 0.0
    assert cu.text_similarity(None, None) == 0.0
```

Criar `tests/test_consistency_text.py` só com o teste do schema por enquanto (o resto vem na Task 2):

```python
"""
Fase 4 da consistência financeira: Camada 5 (trilha temporal) + Camada 4 (similaridade).
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
CNPJ = "84.429.695/0001-11"


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def test_schema_timeline_unique_inclui_classificacao():
    conn = _db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cd_conta_ds_timeline)")]
    assert {"run_id", "cnpj_companhia", "tipo_doc", "cd_conta_pai", "ds_conta_norm", "fonte", "data_referencia",
            "cd_conta", "ds_conta", "st_conta_fixa", "data_referencia_anterior", "cd_conta_anterior",
            "ds_conta_anterior", "similarity_score", "classificacao"} <= set(cols)
    base = ("r", CNPJ, "DFC_MI", "6.01", "x", "DFP", "2023-12-31", "6.01.05", "X", "N")
    conn.execute("INSERT INTO consistency_runs (run_id, layer, check_type) VALUES ('r', 5, 'text_stability')")
    sql = ("INSERT INTO cd_conta_ds_timeline (run_id, cnpj_companhia, tipo_doc, cd_conta_pai, ds_conta_norm, fonte, "
           "data_referencia, cd_conta, ds_conta, st_conta_fixa, classificacao) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    conn.execute(sql, base + ("removida",))
    conn.execute(sql, base + ("nova",))            # mesmo código, classe diferente: permitido (cascata)
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, base + ("nova",))        # duplicata exata: não
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, base + ("inventada",))   # CHECK
```

- [x] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_utils.py tests/test_consistency_text.py -q -k "similarity or schema_timeline" 2>&1 | tail -3
```

Expected: 2 failed (`AttributeError: text_similarity`; `no such table: cd_conta_ds_timeline`).

- [x] **Step 3: Implementar**

`schema.sql`, logo depois de `CREATE INDEX IF NOT EXISTS idx_cflags_run ...;`:

```sql

-- Camada 5 (Fase 4): trilha temporal de cada linha (pai + nome) entre filings
-- consecutivos da mesma fonte. Uma linha por mudança (renumerado, reformulacao,
-- ambiguo, nova, removida) ou primeira ocorrência; 'estavel' não é gravada.
-- 'removida' fica no filing em que a linha sumiu, com cd_conta/ds_conta da linha
-- antiga — por isso a UNIQUE inclui classificacao (o código pode ser reutilizado
-- por outra linha no mesmo filing: renumeração em cascata, 15 mil casos).
CREATE TABLE IF NOT EXISTS cd_conta_ds_timeline (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                   TEXT NOT NULL REFERENCES consistency_runs(run_id),
    cnpj_companhia           TEXT NOT NULL,
    tipo_doc                 TEXT NOT NULL,
    cd_conta_pai             TEXT,                 -- NULL no nível 1
    ds_conta_norm            TEXT NOT NULL,        -- normalize_text(ds_conta)
    fonte                    TEXT NOT NULL,
    data_referencia          TEXT NOT NULL,        -- filing B (atual)
    cd_conta                 TEXT NOT NULL,
    ds_conta                 TEXT,
    st_conta_fixa            TEXT,
    data_referencia_anterior TEXT,                 -- filing A (anterior); NULL em primeira_ocorrencia
    cd_conta_anterior        TEXT,
    ds_conta_anterior        TEXT,
    similarity_score         REAL,                 -- 1.0 em renumerado; score em reformulacao/ambiguo
    classificacao            TEXT NOT NULL CHECK (classificacao IN
        ('primeira_ocorrencia','estavel','renumerado','reformulacao','ambiguo','nova','removida')),
    created_at               TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta, classificacao)
);
CREATE INDEX IF NOT EXISTS idx_timeline_chave ON cd_conta_ds_timeline (cnpj_companhia, tipo_doc, cd_conta_pai, ds_conta_norm);
CREATE INDEX IF NOT EXISTS idx_timeline_class ON cd_conta_ds_timeline (classificacao);
```

`consistency_utils.py`: `import difflib` (stdlib), `"text_similarity"` no `__all__`, e logo depois de `is_outros`:

```python
def text_similarity(a, b) -> float:
    """Similaridade em [0, 1] entre dois nomes de conta (Camada 4): difflib sobre o
    texto normalizado, tomando o maior entre a ordem original e os tokens ordenados
    (token-sort), para que "Empréstimos e Financiamentos" ≈ "Financiamentos e
    Empréstimos". Vazio de um lado → 0.0."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    direto = difflib.SequenceMatcher(None, na, nb).ratio()
    ordenado = difflib.SequenceMatcher(None, " ".join(sorted(na.split())), " ".join(sorted(nb.split()))).ratio()
    return max(direto, ordenado)
```

- [x] **Step 4: Rodar e ver passar; aplicar o schema no banco real (idempotente)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -1 && sqlite3 cvm_research.db < schema.sql && sqlite3 cvm_research.db "SELECT name FROM sqlite_master WHERE name LIKE '%timeline%'"
```

Expected: 135 passed; `cd_conta_ds_timeline`, `idx_timeline_chave`, `idx_timeline_class`.

- [x] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add schema.sql scripts/analysis/consistency_utils.py tests/test_consistency_utils.py tests/test_consistency_text.py && git commit -q -m "feat(analysis): cd_conta_ds_timeline no schema; text_similarity com token-sort (Fase 4)" && git log --oneline -1
```

---

### Task 2: `check_text_stability.py` — lógica pura + CLI

**Files:** `scripts/analysis/check_text_stability.py` (criar), `tests/test_consistency_text.py`

- [x] **Step 1: Testes que falham** — acrescentar a `tests/test_consistency_text.py`:

```python
import check_text_stability as cts


def _doc(contas, data_ref, fonte="DFP", tipo_doc="DFC_MI", ordem="Último"):
    """contas = {cd: (ds, st)}; linhas no formato de latest_rows (vl_conta irrelevante aqui)."""
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": "2023-01-01", "periodo_fim": data_ref,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": 1.0, "st_conta_fixa": st}
            for cd, (ds, st) in contas.items()]


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


A = {"6.01": ("Caixa Líquido Atividades Operacionais", "S"), "6.01.01": ("Caixa Gerado nas Operações", "S"),
     "6.01.01.01": ("Lucro do Período", "N"), "6.01.01.02": ("Depreciação", "N"),
     "6.01.01.03": ("Obrigações pós emprego", "N"), "6.01.01.04": ("Partes relacionadas", "N")}


def _classes(rows):
    return {(r["cd_conta"], r["classificacao"]) for r in rows}


def test_primeiro_filing_e_primeira_ocorrencia():
    rows, flags, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31")))
    assert {r["classificacao"] for r in rows} == {"primeira_ocorrencia"} and len(rows) == 6
    r = [x for x in rows if x["cd_conta"] == "6.01.01.03"][0]
    assert (r["cnpj_companhia"], r["tipo_doc"], r["fonte"], r["data_referencia"]) == (CNPJ, "DFC_MI", "DFP", "2022-12-31")
    assert (r["cd_conta_pai"], r["ds_conta_norm"], r["st_conta_fixa"]) == ("6.01.01", "obrigacoes pos emprego", "N")
    assert r["data_referencia_anterior"] is None and r["cd_conta_anterior"] is None and r["similarity_score"] is None
    assert [x for x in rows if x["cd_conta"] == "6.01"][0]["cd_conta_pai"] == "6"
    assert flags == []
    assert stats == {"DFC_MI": {"filings": 1, "primeira_ocorrencia": 6, "estavel": 0, "renumerado": 0,
                                "reformulacao": 0, "ambiguo": 0, "nova": 0, "removida": 0}}


def test_filing_identico_so_estavel_sem_linhas():
    rows, _, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(A, "2023-12-31")))
    assert {r["classificacao"] for r in rows} == {"primeira_ocorrencia"}
    assert stats["DFC_MI"]["estavel"] == 6 and stats["DFC_MI"]["filings"] == 2


def test_renumerado_por_nome_no_mesmo_pai():
    B = dict(A); B.pop("6.01.01.02"); B["6.01.01.07"] = ("DEPRECIAÇÃO", "N")
    rows, _, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    r, = [x for x in rows if x["data_referencia"] == "2023-12-31"]
    assert (r["cd_conta"], r["classificacao"], r["cd_conta_anterior"], r["ds_conta_anterior"]) == \
        ("6.01.01.07", "renumerado", "6.01.01.02", "Depreciação")
    assert (r["ds_conta"], r["similarity_score"], r["data_referencia_anterior"]) == ("DEPRECIAÇÃO", 1.0, "2022-12-31")


def test_reformulacao_ambiguo_nova_removida_e_flag_de_ambiguo():
    B = dict(A)
    B["6.01.01.03"] = ("Obrigação de benefício pós-emprego", "N")     # score 0,75 → reformulacao (mesmo código)
    B.pop("6.01.01.04"); B["6.01.01.05"] = ("Partes relacionadas e coligadas", "N")   # score alto → reformulacao
    B["6.01.01.06"] = ("Juros pagos", "N")                             # nova
    A2 = dict(A, **{"6.01.01.08": ("Provisão para Bens Não de Uso", "N")})
    B["6.01.01.09"] = ("Imparidade Imobilizado de Uso", "N")            # score ≈ 0,55 → ambiguo
    rows, flags, stats = cts.check_text_stability(_df(_doc(A2, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = {r["cd_conta"]: r for r in rows if r["data_referencia"] == "2023-12-31"}
    assert novos["6.01.01.03"]["classificacao"] == "reformulacao" and novos["6.01.01.03"]["cd_conta_anterior"] == "6.01.01.03"
    assert abs(novos["6.01.01.03"]["similarity_score"] - 0.75) < 0.01
    assert novos["6.01.01.05"]["classificacao"] == "reformulacao" and novos["6.01.01.05"]["cd_conta_anterior"] == "6.01.01.04"
    assert novos["6.01.01.06"]["classificacao"] == "nova" and novos["6.01.01.06"]["cd_conta_anterior"] is None
    assert novos["6.01.01.09"]["classificacao"] == "ambiguo" and novos["6.01.01.09"]["cd_conta_anterior"] == "6.01.01.08"
    assert 0.45 < novos["6.01.01.09"]["similarity_score"] < 0.75
    assert stats["DFC_MI"]["reformulacao"] == 2 and stats["DFC_MI"]["ambiguo"] == 1 and stats["DFC_MI"]["nova"] == 1
    f, = flags
    assert (f["layer"], f["check_type"], f["classificacao"], f["severity"], f["cd_conta"]) == \
        (5, "text_stability", "ambiguo", "warn", "6.01.01.09")
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("DFP", "2022-12-31", "DFP", "2023-12-31")
    assert f["detalhe"] == {"score": novos["6.01.01.09"]["similarity_score"], "cd_conta_anterior": "6.01.01.08",
                            "ds_conta_anterior": "Provisão para Bens Não de Uso"}


def test_removida_com_codigo_reutilizado_gera_duas_linhas():
    # cascata: Depreciação some; Obrigações desce para o código dela
    B = dict(A); B.pop("6.01.01.03"); B["6.01.01.02"] = ("Obrigações pós emprego", "N")
    rows, _, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = _classes([r for r in rows if r["data_referencia"] == "2023-12-31"])
    assert novos == {("6.01.01.02", "renumerado"), ("6.01.01.02", "removida")}
    rem = [r for r in rows if r["classificacao"] == "removida"][0]
    assert (rem["ds_conta"], rem["cd_conta_anterior"], rem["ds_conta_anterior"], rem["data_referencia_anterior"]) == \
        ("Depreciação", "6.01.01.02", "Depreciação", "2022-12-31")


def test_linha_S_mesmo_codigo_e_estavel_mesmo_com_nome_diferente_e_nunca_ambigua():
    B = dict(A); B["6.01.01"] = ("Caixa Gerado nas Operações Continuadas", "S")
    rows, _, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    assert [r for r in rows if r["data_referencia"] == "2023-12-31"] == [] and stats["DFC_MI"]["estavel"] == 6
    B = dict(A); B.pop("6.01.01"); B["6.01.02"] = ("Caixa Gerado nas Operações Continuadas", "S")   # S sem par por nome
    rows, flags, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = _classes([r for r in rows if r["data_referencia"] == "2023-12-31"])
    assert ("6.01.02", "nova") in novos and ("6.01.01", "removida") in novos and flags == []


def test_pai_renumerado_leva_os_filhos_junto():
    B = {"6.01": A["6.01"], "6.01.02": ("Caixa Gerado nas Operações", "S"),
         "6.01.02.01": ("Lucro do Período", "N"), "6.01.02.02": ("Depreciação", "N"),
         "6.01.02.03": ("Obrigações pós emprego", "N"), "6.01.02.04": ("Partes relacionadas", "N")}
    rows, _, stats = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = {r["cd_conta"]: r for r in rows if r["data_referencia"] == "2023-12-31"}
    assert {r["classificacao"] for r in novos.values()} == {"renumerado"} and len(novos) == 5
    assert novos["6.01.02.03"]["cd_conta_anterior"] == "6.01.01.03" and novos["6.01.02"]["cd_conta_anterior"] == "6.01.01"
    assert stats["DFC_MI"]["nova"] == 0 and stats["DFC_MI"]["removida"] == 0


def test_pai_removido_leva_os_filhos_e_pai_novo_traz_filhos_novos():
    B = {"6.01": A["6.01"], "6.03": ("Caixa Líquido Atividades de Financiamento", "S"), "6.03.01": ("Dividendos", "N")}
    rows, _, _ = cts.check_text_stability(_df(_doc(A, "2022-12-31"), _doc(B, "2023-12-31")))
    novos = _classes([r for r in rows if r["data_referencia"] == "2023-12-31"])
    assert ("6.01.01", "removida") in novos and ("6.01.01.01", "removida") in novos
    assert ("6.03", "nova") in novos and ("6.03.01", "nova") in novos


def test_sequencias_separadas_por_fonte_e_tipo_e_penultimo_ignorado():
    df = _df(_doc(A, "2022-12-31"), _doc(A, "2023-03-31", fonte="ITR"), _doc(A, "2022-12-31", ordem="Penúltimo"),
             _doc({"3.01": ("Receita", "S")}, "2022-12-31", tipo_doc="DRE"))
    rows, _, stats = cts.check_text_stability(df)
    assert {r["classificacao"] for r in rows} == {"primeira_ocorrencia"} and len(rows) == 13
    assert stats["DFC_MI"]["filings"] == 2 and stats["DRE"]["filings"] == 1
    assert cts.check_text_stability(pd.DataFrame()) == ([], [], {})


def test_limiares_parametrizados():
    A2 = dict(A, **{"6.01.01.08": ("Provisão para Bens Não de Uso", "N")})
    B = dict(A, **{"6.01.01.09": ("Imparidade Imobilizado de Uso", "N")})       # score ≈ 0,55
    rows, _, _ = cts.check_text_stability(_df(_doc(A2, "2022-12-31"), _doc(B, "2023-12-31")), sim_alto=0.5)
    assert [r["classificacao"] for r in rows if r["data_referencia"] == "2023-12-31"] == ["reformulacao"]
    rows, _, _ = cts.check_text_stability(_df(_doc(A2, "2022-12-31"), _doc(B, "2023-12-31")), sim_baixo=0.6)
    assert _classes([r for r in rows if r["data_referencia"] == "2023-12-31"]) == {("6.01.01.09", "nova"), ("6.01.01.08", "removida")}


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

def _db_com_docs():
    conn = _db()
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    A2 = dict(A, **{"6.01.01.08": ("Provisão para Bens Não de Uso", "N")})
    B = dict(A); B.pop("6.01.01.02"); B["6.01.01.07"] = ("Depreciação", "N"); B["6.01.01.09"] = ("Imparidade Imobilizado de Uso", "N")
    rows = _doc(A2, "2022-12-31") + _doc(B, "2023-12-31")
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r["periodo_ini"] if c == "dt_ini_exerc" else r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols)
         for r in rows],
    )
    conn.commit()
    return conn


def test_main_grava_timeline_flags_e_substitui(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(cts, "get_db", lambda: conn)
    run1 = cts.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT classificacao, COUNT(*) FROM cd_conta_ds_timeline WHERE run_id = ? GROUP BY 1 ORDER BY 1",
                       (run1,)).fetchall()
    assert got == [("ambiguo", 1), ("primeira_ocorrencia", 7), ("renumerado", 1)]
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags WHERE run_id = ? AND layer = 5 AND classificacao = 'ambiguo'",
                        (run1,)).fetchone()[0] == 1
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, script_args FROM consistency_runs "
                       "WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (5, "text_stability", f"cnpj={CNPJ}", 2, 9)      # 2 filings; 9 linhas na timeline
    assert '"sim_alto": 0.75' in run[5]
    run2 = cts.main(["--cnpj", CNPJ, "--tipo-doc", "DFC_MI"])
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM cd_conta_ds_timeline").fetchone() == (9, 1)
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags").fetchone() == (1, 1)
    assert conn.execute("SELECT DISTINCT run_id FROM cd_conta_ds_timeline").fetchone()[0] == run2
    out = capsys.readouterr().out
    assert "DFC_MI" in out and "filings=2" in out and "renumerado=1" in out and "ambiguo=1" in out


def test_main_full_e_exigencia_de_cnpj(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(cts, "get_db", lambda: conn)
    run_id = cts.main(["--full", "--sim-alto", "0.5"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    assert conn.execute("SELECT COUNT(*) FROM cd_conta_ds_timeline WHERE classificacao = 'reformulacao'").fetchone()[0] == 1
    import pytest
    with pytest.raises(SystemExit):
        cts.main([])
```

- [x] **Step 2: Rodar e ver falhar**: `pytest tests/test_consistency_text.py -q` → `ModuleNotFoundError: check_text_stability`.

- [x] **Step 3: Criar `scripts/analysis/check_text_stability.py`**

```python
"""
Camada 5 — trilha temporal de linhas (check_type = 'text_stability'), com a
Camada 4 (similaridade textual, consistency_utils.text_similarity) embutida.

Para cada (cnpj, tipo_doc, fonte), percorre os filings em ordem de
data_referencia (ordem_exercicio = 'Último', versão máxima, uma linha por
código) e compara cada filing B com o anterior A, de cima para baixo na
hierarquia: os pais casados num nível definem quais conjuntos de filhos se
comparam no nível seguinte (um pai renumerado leva os filhos junto). Dentro de
cada pai:
  0. 'S' com o mesmo código dos dois lados → 'estavel' (código fixo pela CVM; não grava)
  1. mesmo normalize_text(ds_conta): mesmo código → 'estavel'; outro código → 'renumerado'
  2. sobras 'N' dos dois lados: pareamento guloso por maior text_similarity;
     score ≥ sim_alto → 'reformulacao'; sim_baixo < score < sim_alto → 'ambiguo'
     (fila de revisão: também vira flag layer 5 em consistency_flags)
  3. sobras de B → 'nova'; sobras de A → 'removida' ('S' nunca entra na similaridade)
Pai de A sem par em B → filhos 'removida'; pai de B sem par → filhos 'nova'.
Primeiro filing de cada sequência → 'primeira_ocorrencia' para todas as linhas.

Grava em cd_conta_ds_timeline (data_referencia = filing B; 'removida' com
cd_conta/ds_conta da linha antiga; cd_conta_anterior/ds_conta_anterior/
similarity_score quando há par) e em consistency_flags só os 'ambiguo'.
Linhas anteriores do mesmo (cnpj[, tipo_doc]) são apagadas nas duas tabelas
antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) depois da Camada 3. À mão
(na pasta scripts/analysis, .venv ativo):
  python check_text_stability.py --cnpj 84.429.695/0001-11
  python check_text_stability.py --cnpj 84.429.695/0001-11 --tipo-doc DFC_MI --sim-alto 0.8
  python check_text_stability.py --full          # base inteira (~145 empresas, ~2 min)
"""
import pandas as pd

from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows, new_run,
                               normalize_text, parent_code, text_similarity, write_flags)

LAYER = 5
CHECK_TYPE = "text_stability"
SIM_ALTO, SIM_BAIXO = 0.75, 0.45
CLASSES = ["primeira_ocorrencia", "estavel", "renumerado", "reformulacao", "ambiguo", "nova", "removida"]
TIMELINE_COLS = ["run_id", "cnpj_companhia", "tipo_doc", "cd_conta_pai", "ds_conta_norm", "fonte", "data_referencia",
                 "cd_conta", "ds_conta", "st_conta_fixa", "data_referencia_anterior", "cd_conta_anterior",
                 "ds_conta_anterior", "similarity_score", "classificacao"]


def _texto(v):
    return v if isinstance(v, str) else None


def _linhas(doc: pd.DataFrame) -> dict:
    """{cd_conta: (ds_conta, st_conta_fixa)} de um filing — uma entrada por código
    (a DRE do ITR repete o código por período)."""
    out: dict = {}
    for r in doc.itertuples(index=False):
        out.setdefault(r.cd_conta, (_texto(r.ds_conta), _texto(r.st_conta_fixa)))
    return out


def _row(cd: str, ds, st, classe: str, anterior=None, score=None) -> dict:
    return {"cd_conta": cd, "cd_conta_pai": parent_code(cd), "ds_conta": ds, "ds_conta_norm": normalize_text(ds),
            "st_conta_fixa": st, "cd_conta_anterior": anterior[0] if anterior else None,
            "ds_conta_anterior": anterior[1] if anterior else None, "similarity_score": score,
            "classificacao": classe}


def _comparar_pai(fa: dict, fb: dict, sim_alto: float, sim_baixo: float) -> tuple[list[dict], dict, int]:
    """fa/fb = {cd: (ds, st)}: filhos diretos de um pai em A e em B.
    Retorna (rows, mapa código A → código B das linhas casadas, n_estaveis)."""
    rows: list[dict] = []
    mapa: dict = {}
    estaveis = 0
    # 0. 'S' com o mesmo código: estável por definição da CVM
    for cd, (ds, st) in fa.items():
        if st == "S" and cd in fb and fb[cd][1] == "S":
            mapa[cd] = cd
            estaveis += 1
    # 1. nome normalizado
    na: dict = {}
    nb: dict = {}
    for cd, (ds, st) in fa.items():
        if cd not in mapa:
            na.setdefault(normalize_text(ds), []).append(cd)
    for cd, (ds, st) in fb.items():
        if cd not in mapa:
            nb.setdefault(normalize_text(ds), []).append(cd)
    sobra_a: list[str] = []
    sobra_b: list[str] = []
    for nome in list(na) + [k for k in nb if k not in na]:
        a, b = na.get(nome, []), nb.get(nome, [])
        comuns = [cd for cd in a if cd in b]
        for cd in comuns:
            mapa[cd] = cd
            estaveis += 1
        ra = [cd for cd in a if cd not in comuns]
        rb = [cd for cd in b if cd not in comuns]
        for x, y in zip(ra, rb):
            mapa[x] = y
            rows.append(_row(y, fb[y][0], fb[y][1], "renumerado", (x, fa[x][0]), 1.0))
        sobra_a += ra[len(rb):]
        sobra_b += rb[len(ra):]
    # 2. similaridade só entre linhas 'N'
    cand_a = [cd for cd in sobra_a if fa[cd][1] != "S"]
    cand_b = [cd for cd in sobra_b if fb[cd][1] != "S"]
    pares = sorted(((text_similarity(fa[x][0], fb[y][0]), x, y) for x in cand_a for y in cand_b),
                   key=lambda t: (-t[0], t[1], t[2]))
    usados_a: set = set()
    usados_b: set = set()
    for score, x, y in pares:
        if score <= sim_baixo:
            break
        if x in usados_a or y in usados_b:
            continue
        usados_a.add(x)
        usados_b.add(y)
        mapa[x] = y
        rows.append(_row(y, fb[y][0], fb[y][1], "reformulacao" if score >= sim_alto else "ambiguo",
                         (x, fa[x][0]), round(score, 4)))
    # 3. sobras
    for cd in sobra_b:
        if cd not in usados_b:
            rows.append(_row(cd, fb[cd][0], fb[cd][1], "nova"))
    for cd in sobra_a:
        if cd not in usados_a:
            rows.append(_row(cd, fa[cd][0], fa[cd][1], "removida", (cd, fa[cd][0])))
    return rows, mapa, estaveis


def _nivel(pai) -> tuple:
    return (-1, "") if pai is None else (pai.count("."), pai)


def compare_filings(A: dict, B: dict, sim_alto: float = SIM_ALTO, sim_baixo: float = SIM_BAIXO) -> tuple[list[dict], int]:
    """A/B = {cd: (ds, st)} de dois filings consecutivos. Retorna (rows sem contexto, n_estaveis).
    Processa os pais da raiz para as folhas; o mapa A→B dos pais já casados escolhe
    os filhos de A que correspondem a cada pai de B."""
    filhos_a: dict = {}
    filhos_b: dict = {}
    for cd, v in A.items():
        filhos_a.setdefault(parent_code(cd), {})[cd] = v
    for cd, v in B.items():
        filhos_b.setdefault(parent_code(cd), {})[cd] = v
    rows: list[dict] = []
    mapa: dict = {}
    consumidos: set = set()
    estaveis = 0
    for pb in sorted(filhos_b, key=_nivel):
        inverso = {v: k for k, v in mapa.items()}
        if pb in inverso:
            pa = inverso[pb]            # pai casado (estável ou renumerado) no nível acima
        elif pb in mapa:
            pa = None                   # o pai de A com esse código foi para outro lugar
        else:
            pa = pb                     # código literal (inclusive pais que não são linha, ex: '3')
        fa = filhos_a.get(pa, {}) if pa is not None and pa not in consumidos else {}
        if fa:
            consumidos.add(pa)
        r, m, n = _comparar_pai(fa, filhos_b[pb], sim_alto, sim_baixo)
        rows += r
        mapa.update(m)
        estaveis += n
    for pa, fa in filhos_a.items():
        if pa not in consumidos:
            rows += [_row(cd, ds, st, "removida", (cd, ds)) for cd, (ds, st) in fa.items()]
    return rows, estaveis


def check_text_stability(df: pd.DataFrame, sim_alto: float = SIM_ALTO,
                         sim_baixo: float = SIM_BAIXO) -> tuple[list[dict], list[dict], dict]:
    """df = saída de latest_rows. Retorna (rows da timeline, flags de 'ambiguo', stats).
    stats[tipo_doc] = {"filings": n, <classe>: n_linhas} (estavel contada, não gravada)."""
    rows: list[dict] = []
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return rows, flags, stats
    df = df[df["ordem_exercicio"] == "Último"]
    for (cnpj, tipo_doc, fonte), grupo in df.groupby(["cnpj_companhia", "tipo_doc", "fonte"], sort=True):
        st = stats.setdefault(tipo_doc, {"filings": 0, **{c: 0 for c in CLASSES}})
        anterior = None
        for data_ref in sorted(grupo["data_referencia"].unique()):
            atual = _linhas(grupo[grupo["data_referencia"] == data_ref])
            st["filings"] += 1
            contexto = {"cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "fonte": fonte, "data_referencia": data_ref}
            if anterior is None:
                novas = [_row(cd, ds, s, "primeira_ocorrencia") for cd, (ds, s) in atual.items()]
                rows += [{**contexto, "data_referencia_anterior": None, **r} for r in novas]
                st["primeira_ocorrencia"] += len(novas)
            else:
                data_ant, linhas_ant = anterior
                novas, estaveis = compare_filings(linhas_ant, atual, sim_alto, sim_baixo)
                st["estavel"] += estaveis
                for r in novas:
                    st[r["classificacao"]] += 1
                    rows.append({**contexto, "data_referencia_anterior": data_ant, **r})
                    if r["classificacao"] == "ambiguo":
                        flags.append({
                            "layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "ambiguo", "severity": "warn",
                            "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
                            "cd_conta": r["cd_conta"], "cd_conta_pai": r["cd_conta_pai"], "ds_conta": r["ds_conta"],
                            "fonte_ref": fonte, "data_ref": data_ant, "ordem_ref": "Último",
                            "fonte_cmp": fonte, "data_cmp": data_ref, "ordem_cmp": "Último",
                            "detalhe": {"score": r["similarity_score"], "cd_conta_anterior": r["cd_conta_anterior"],
                                        "ds_conta_anterior": r["ds_conta_anterior"]},
                        })
            anterior = (data_ref, atual)
    return rows, flags, stats


# ── Escrita ──────────────────────────────────────────────────────────────────

def clear_timeline(conn, cnpj: str, tipo_doc: str | None = None) -> int:
    sql = "DELETE FROM cd_conta_ds_timeline WHERE cnpj_companhia = ?"
    params: list = [cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        params.append(tipo_doc)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def write_timeline(conn, run_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = (f"INSERT INTO cd_conta_ds_timeline ({','.join(TIMELINE_COLS)}) "
           f"VALUES ({','.join('?' * len(TIMELINE_COLS))})")
    try:
        conn.executemany(sql, [tuple(run_id if c == "run_id" else r.get(c) for c in TIMELINE_COLS) for r in rows])
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
    """Roda a Camada 5 e devolve o run_id. `argv=None` lê sys.argv."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--sim-alto", dest="sim_alto", type=float, default=SIM_ALTO,
                        help="score mínimo para 'reformulacao' (padrão 0.75)")
    parser.add_argument("--sim-baixo", dest="sim_baixo", type=float, default=SIM_BAIXO,
                        help="score máximo para 'nova'/'removida' (padrão 0.45); entre os dois é 'ambiguo'")
    args = parser.parse_args(argv)
    if not args.cnpj and not args.full:
        parser.error("informe --cnpj ou confirme a base inteira com --full")

    conn = get_db()
    if args.cnpj:
        cnpjs = [args.cnpj]
    else:
        cnpjs = [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
    run_id = new_run(conn, LAYER, CHECK_TYPE, _escopo(args), vars(args))
    print(f"run {run_id}: {len(cnpjs)} empresa(s), sim_alto={args.sim_alto} sim_baixo={args.sim_baixo}")

    total_checked = total_flagged = 0
    stats_total: dict = {}
    for i, cnpj in enumerate(cnpjs, 1):
        df = latest_rows(conn, cnpj=cnpj, tipo_doc=args.tipo_doc, desde=args.desde, ate=args.ate)
        rows, flags, stats = check_text_stability(df, args.sim_alto, args.sim_baixo)
        clear_timeline(conn, cnpj, args.tipo_doc)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_timeline(conn, run_id, rows)
        write_flags(conn, run_id, flags)
        filings = sum(s["filings"] for s in stats.values())
        total_checked += filings
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {filings} filings, {n} linhas na timeline, "
              f"{len(flags)} ambiguas")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (filings = documentos 'Último' por fonte; estavel não é gravada):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        print(f"  {tipo:7s} filings={s['filings']} " + " ".join(f"{c}={s[c]}" for c in CLASSES))
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Rodar e ver passar**: `pytest tests/test_consistency_text.py -q` → 14 passed.

- [x] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/check_text_stability.py tests/test_consistency_text.py && git commit -q -m "feat(analysis): Camada 5 — check_text_stability (trilha temporal por pai + nome, similaridade com token-sort)" && git log --oneline -1
```

---

### Task 3: `run_all.py` + `update_weekly.sh`

- [x] **Step 1:** `run_all.py`: `import check_text_stability`; `5: check_text_stability.main` no `LAYERS`; docstring `(5 = trilha temporal, 6 = desacúmulo)` → `(6 = desacúmulo; a Camada 4, similaridade, está dentro da 5)`; `para N = 1, 2, 3` → `para N = 1, 2, 3, 5`.
- [x] **Step 2:** `update_weekly.sh`: `run_step "consistency_l5" ../analysis/run_all.py --layer 5 --full` depois de `consistency_l3`; comentário `e Camada 3 (linhas sem par entre filings)` → `, Camada 3 (linhas sem par entre filings) e Camada 5 (trilha temporal de nomes/códigos)`; cabeçalho `(Camadas 1 a 3)` → `(Camadas 1 a 5)`.
- [x] **Step 3:** conferir `--help` (`disponíveis: 1,2,3,5`), `bash -n`, suíte (149 passed); commit `feat(analysis): run_all --layer 5; Camada 5 no update_weekly.sh`.

---

### Task 4: Fumaça na WEG

- [x] **Step 1:** rodar `run_all.py --layer 5 --cnpj 84.429.695/0001-11` duas vezes; conferir: contagens por classe plausíveis, `SELECT COUNT(*), COUNT(DISTINCT run_id)` na timeline da WEG = 1 run; flags de layer 1–3 intactas; amostra de `renumerado` da DFC 6.01.02 entre ITR 3T22 e 3T23 (o caso de cascata da Fase 3) mostrando `cd_conta_anterior` deslocado.

---

### Task 5: Base inteira, revisão dos ambíguos e decisão dos cortes

- [x] **Step 1:** `run_all.py --layer 5 --full` (medir tempo); consultas: total por classe; DFC_MI/DFP por classe (esperado: renumerado ≈ 3,7 mil, reformulacao ≈ 3,7 mil, ambiguo ≈ 2,3 mil, removida ≈ 3 mil, nova ≈ 5,6 mil — antes do token-sort); histograma de `similarity_score` dos ambíguos em faixas de 0,05.
- [x] **Step 2:** amostrar 50 `ambiguo` estratificados por faixa de score (0,45–0,55, 0,55–0,65, 0,65–0,75) e julgar à mão se são a mesma linha. Decidir os cortes: se a faixa 0,45–0,60 for majoritariamente errada e 0,60–0,75 majoritariamente certa, avaliar `sim_baixo = 0,60`; registrar a decisão e a amostra no plano-mãe. Se os cortes mudarem, alterar `SIM_BAIXO`/`SIM_ALTO`, rodar a suíte, rerodar `--full` e registrar os números finais.
- [x] **Step 3:** pergunta-alvo via SQL: "quantas linhas da DFC da empresa X foram renumeradas, reformuladas ou removidas nos últimos 5 anos" (WEG) — guardar a query para o CLAUDE.md.
- [x] **Step 4:** ponteiro + números + decisão no plano-mãe; commit `docs(plano): numeros medidos da Camada 5 e decisao dos limiares; ponteiro para o plano da Fase 4`.

---

### Task 6: Documentação

- [x] **Step 1: `CLAUDE.md`** — nova subseção depois de `consistency_flags` (antes de `---`):

```markdown
### `cd_conta_ds_timeline` — trilha temporal de cada linha (pai + nome) entre filings (Camada 5)
`run_id, cnpj_companhia, tipo_doc, fonte, data_referencia (filing atual), cd_conta, ds_conta, st_conta_fixa, cd_conta_pai,`
`ds_conta_norm, data_referencia_anterior, cd_conta_anterior, ds_conta_anterior, similarity_score, classificacao`

Filings consecutivos da mesma fonte (`ordem_exercicio = 'Último'`), comparados de cima para baixo na hierarquia
(pai renumerado leva os filhos junto). Uma linha por mudança; `estavel` **não é gravada**:
- `primeira_ocorrencia`: todas as linhas do primeiro filing da sequência.
- `renumerado` (`similarity_score = 1`): mesmo nome normalizado em código diferente — `cd_conta_anterior` diz de onde veio.
- `reformulacao` (score ≥ 0,75) e `ambiguo` (0,45 < score < 0,75; também vira flag `layer = 5` em `consistency_flags`,
  fila de revisão): nome parecido (difflib com token-sort sobre texto normalizado), só em linhas `st_conta_fixa = 'N'`.
- `nova` / `removida`: sem par. `removida` fica no filing em que sumiu, com `cd_conta`/`ds_conta` da linha antiga
  (o código pode ter sido reutilizado por outra linha no mesmo filing — renumeração em cascata).
Contas `S` (padrão CVM) com o mesmo código são estáveis mesmo que o nome mude.
```

Query padrão, depois da query da Camada 3:

```markdown
### O que aconteceu com as linhas de um demonstrativo ao longo do tempo (Camada 5)
```sql
-- Quantas linhas da DFC foram renumeradas, reformuladas ou removidas nos últimos 5 anos
SELECT classificacao, COUNT(*) AS linhas
FROM cd_conta_ds_timeline
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DFC_MI' AND fonte = 'DFP'
  AND data_referencia >= date('now', '-5 years')
  AND classificacao IN ('renumerado', 'reformulacao', 'ambiguo', 'removida')
GROUP BY 1 ORDER BY 2 DESC;

-- Trilha de uma conta: por onde ela passou (código e nome) filing a filing
SELECT data_referencia, cd_conta, ds_conta, classificacao, cd_conta_anterior, ds_conta_anterior, similarity_score
FROM cd_conta_ds_timeline
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DFC_MI' AND fonte = 'DFP'
  AND (ds_conta_norm = '<nome normalizado>' OR cd_conta = '<código>' OR cd_conta_anterior = '<código>')
ORDER BY data_referencia;
```
Ausência de linhas para um filing significa que nada mudou nele (todas as linhas `estavel`). Para comparar valores de
uma conta que foi renumerada, use `cd_conta_anterior` para buscar o código antigo nos filings anteriores.
```

Item 11 no "Comportamento esperado ao pesquisar": `**Série histórica de uma conta criada pela empresa (`st_conta_fixa = 'N'`)**: antes de montar a série por `cd_conta`, confira em `cd_conta_ds_timeline` se o código foi renumerado ou reformulado no período; monte a série pelo nome normalizado (`ds_conta_norm`) + pai, seguindo `cd_conta_anterior`, e informe os anos em que a linha foi `ambiguo` ou `removida`.`

Em `## Defasagem dos dados`: `consistência (Camada 2)` → `consistência (Camadas 1, 2, 3 e 5)`.

- [x] **Step 2: `README.md`** — árvore (`check_text_stability.py  # Camada 5 (+4): trilha temporal de nomes/códigos por pai`), `As Camadas 1, 2 e 3 rodam` → `As Camadas 1, 2, 3 e 5 rodam`, exemplo `--layer 1,2,3` → `--layer 1,2,3,5`, linha na tabela: `| 5 (+4) | `check_text_stability.py` | Trilha temporal de cada linha (pai + nome) entre filings consecutivos em `cd_conta_ds_timeline`: `renumerado`, `reformulacao`/`ambiguo` (similaridade textual), `nova`, `removida`. |`.
- [x] **Step 3: `scripts/mcp/cvm_mcp.py`** — lista de tabelas: `consistency_runs, consistency_flags, cd_conta_ds_timeline.`; e depois da descrição de layer=3: `layer=5 text_stability: ambiguo (fila de revisão da similaridade). cd_conta_ds_timeline: trilha de cada linha (pai + nome) entre filings — renumerado/reformulacao/ambiguo/nova/removida com cd_conta_anterior.`
- [x] **Step 4:** `ast.parse` do MCP, suíte, commit `docs: Camada 5 (cd_conta_ds_timeline) no CLAUDE.md, README e docstring do MCP`.

---

## Verificação geral da Fase 4

- `pytest tests/` verde; `schema.sql` aplicado no banco real (idempotente).
- `run_all.py --layer 5 --full` executado; números e decisão dos cortes no plano-mãe.
- Flags das Camadas 1–3 intactas; rerun substitui.
- `update_weekly.sh` passa `bash -n`; passo `consistency_l5` independente.
