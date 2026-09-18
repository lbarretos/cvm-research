# Fase 3 — Camada 3 (granularidade entre filings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Expande a seção "Fase 3" do plano-mãe `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` em tarefas com código, seguindo o precedente das Fases 1 e 2. Pré-requisito: Fases 1 e 2 mescladas em `main` (confirmado em 2026-09-18, merge do PR #13, commit `7190195`).

**Goal:** Criar a Camada 3, que pega as linhas que existem só num dos dois filings de um par da Camada 2 (mesmo período, baseline × filing posterior) e explica cada uma, por pai: `renumerado` (mesmo nome ou mesmo valor em código diferente), `zero_padding` (valor ≈ 0), `reclassificado_em_outros` (absorvida por uma linha "Outros"/"Demais"), `reclassificado_em_irmao` (absorvida por um irmão nomeado, pai inalterado) ou `divergencia_nao_explicada` (o valor saiu do pai).

**Architecture:** `check_cross_period.py` ganha `iter_pairs(df)` (o agrupamento por período + baseline que a Camada 2 já faz) e passa a usá-lo; `check_granularity.py` reaproveita o gerador e resolve os exclusivos pai a pai numa cadeia de seis passos (`_resolver_pai`), com uma flag por linha exclusiva (ou por par casado por nome) mais uma flag-resumo por par. `consistency_utils.py` ganha `normalize_text` (também usada na Fase 4) e `is_outros`. Mesmo CLI, idempotência por `(cnpj[, tipo_doc])` e passo `consistency_l3` no `update_weekly.sh`.

**Tech Stack:** Python 3.14 (`.venv`), `pandas` 2.2, `numpy`, `unicodedata`/`re` (stdlib), `sqlite3` 3.50, `pytest` 8.3.

---

## Decisões de desenho verificadas contra o banco (2026-09-18, protótipo no scratchpad sobre a base inteira)

| Ponto | O que a base mostra | Decisão |
|---|---|---|
| Volume de exclusivos | 15.396 dos 36.531 pares da Camada 2 têm código sem par (BPA 3.120, BPP 3.359, DFC_MI 5.058, DRE 2.513, DVA 1.346). Nos pares BPA DFP(Y) × ITR 1T(Y+1): **620 de 1.746 (35%)**, não os 267 (15%) estimados antes da Fase 0. | Registrar o número medido; a Camada 3 grava uma flag-resumo por par com exclusivos. |
| Casamento por nome | Só **573** linhas casam por nome normalizado (acentos, caixa, pontuação); exigir `st_conta_fixa` igual não perde nenhum casamento (0). | Passo 1 exatamente como no plano-mãe: nome normalizado + `st_conta_fixa` igual (NULL = NULL). |
| `zero_padding` | **33.258** linhas exclusivas têm \|valor\| < R$ 1.000 (NULL = 0) — a classe dominante. | Passo 2 como no plano-mãe. |
| "Outros" | 505 linhas fecham com o delta de uma linha "Outros"/"Demais" comum; em 3.248 casos a própria linha "Outros" é a exclusiva. Regex `\b(outr[oa]s?\|demais)\b` sobre texto normalizado não casa "Opções outorgadas". | Passo 3: as linhas "Outros" entram no balanço dos dois lados (comuns **e** exclusivas, ausente = 0); se fecha, todas as exclusivas restantes do pai viram `reclassificado_em_outros`. |
| Renumeração com nome diferente | 128 linhas somam o mesmo valor dos dois lados sem "Outros" envolvido (ex: "Dividendos Pagos" → "Dividendos pagos e a pagar", mesmo valor). | Passo 4 (novo): exclusivos dos dois lados com somas iguais → `renumerado` com `detalhe.casamento = 'valor'` (por nome é `'nome'`). |
| Pai inalterado | **10.780** linhas exclusivas sem explicação por nome/zero/"Outros" ficam sob um pai comum cujo total não mudou: o valor foi absorvido por um irmão nomeado (reclassificação dentro do pai). Marcar isso como `error` esconderia os casos reais. | Passo 5 (classe nova): `reclassificado_em_irmao` (`warn`), `detalhe.irmaos_alterados` lista os irmãos comuns cujo valor mudou. |
| Pai mudou ou raiz | 11.654 linhas: o valor saiu do pai (mudou de pai ou faz parte de uma reapresentação — 2.967 delas em pares `reapresentacao` da Camada 2). | Passo 6: `divergencia_nao_explicada` (`error`), com `pai_ref`/`pai_cmp` no detalhe. |
| Filhos de pai exclusivo | 2.207 linhas exclusivas cujo pai também é exclusivo (subárvore nova/removida inteira). | Não geram flag (o pai já é resolvido um nível acima); só contam em `detalhe.filhos_de_pai_exclusivo` do resumo. Pai ausente dos dois lados (ex: `3` na DRE) conta como raiz e é resolvido normalmente. |
| `st_conta_fixa` NULL | 658 linhas, todas em ITR 2026 (646) e DFP 2023 (12). | Nenhum tratamento especial: NULL casa com NULL. |

Ordem de resolução por pai (comum aos dois docs, ou raiz), depois de separar os exclusivos:
1. **nome** → `renumerado` (info), uma flag por par casado, `cd_conta = cd_ref`, `detalhe = {casamento: 'nome', cd_ref, cd_cmp}`;
2. **zero** (\|valor\| < `tol_abs`) → `zero_padding` (info);
3. **Outros**: se existe alguma linha "Outros" entre os filhos do pai (em qualquer lado) e `Σ exclusivos_ref − Σ exclusivos_cmp ≈ Σ Outros_cmp − Σ Outros_ref` (exclusivos e Outros sem sobreposição) → `reclassificado_em_outros` (warn);
4. **valor**: exclusivos nos dois lados com `Σ ref ≈ Σ cmp` → `renumerado` (info, `casamento: 'valor'`);
5. **irmão**: pai comum com `pai_ref ≈ pai_cmp` → `reclassificado_em_irmao` (warn);
6. senão → `divergencia_nao_explicada` (error).

"≈" é `|a − b| ≤ max(tol_abs, tol_rel × max(|a|, |b|))`. Flags de linha exclusiva trazem `valor_ref` **ou** `valor_cmp` (o outro lado NULL) e `detalhe.exclusivo_em ∈ {'ref','cmp'}`. Flag-resumo por par (`cd_conta` NULL): `classificacao` = classe mais grave presente, `detalhe = {linhas_exclusivas_ref, linhas_exclusivas_cmp, filhos_de_pai_exclusivo, <contagem por classe>}`.

## Estrutura de arquivos

- **Modify:** `scripts/analysis/consistency_utils.py` — `normalize_text`, `OUTROS_RE`, `is_outros`; `__all__`.
- **Modify:** `scripts/analysis/check_cross_period.py` — extrai `iter_pairs(df)`; `check_cross_period` passa a usá-lo (comportamento idêntico).
- **Create:** `scripts/analysis/check_granularity.py` — `compare_granularity` (um par), `_resolver_pai`, `check_granularity` (DataFrame → flags + stats), `main`.
- **Modify:** `scripts/analysis/run_all.py` — registra a camada 3.
- **Modify:** `scripts/update_weekly.sh` — passo `consistency_l3` depois de `consistency_l2`.
- **Modify:** `tests/test_consistency_utils.py` (normalize_text/is_outros), `tests/test_consistency_cross_period.py` (iter_pairs).
- **Create:** `tests/test_consistency_granularity.py`.
- **Modify:** `CLAUDE.md`, `README.md`, `scripts/mcp/cvm_mcp.py`, plano-mãe (ponteiro + números medidos).

---

### Task 0: Branch de trabalho

- [ ] **Step 1: Criar o branch a partir de `main` limpo**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git status --short && git checkout -b fase-3-camada-3
```

Expected: `git status --short` vazio; `Switched to a new branch 'fase-3-camada-3'`.

---

### Task 1: `consistency_utils.py` — `normalize_text` e `is_outros`; `check_cross_period.py` — `iter_pairs`

**Files:**
- Modify: `scripts/analysis/consistency_utils.py`, `scripts/analysis/check_cross_period.py`
- Test: `tests/test_consistency_utils.py`, `tests/test_consistency_cross_period.py`

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_consistency_utils.py`, logo antes de `# ── latest_rows`:

```python
# ── normalize_text / is_outros (Fase 3) ──────────────────────────────────────

def test_normalize_text_acentos_caixa_pontuacao_e_nulos():
    assert cu.normalize_text("  Provisões p/ Contingências (Líquido)  ") == "provisoes p contingencias liquido"
    assert cu.normalize_text("CONTAS A RECEBER") == cu.normalize_text("Contas a receber")
    assert cu.normalize_text(None) == "" and cu.normalize_text(float("nan")) == ""


def test_is_outros_regex():
    assert cu.is_outros("Outros") and cu.is_outros("Outras Receitas Operacionais") and cu.is_outros("Demais contas")
    assert cu.is_outros("OUTRO ativo") and cu.is_outros("Outra Provisão")
    assert not cu.is_outros("Opções Outorgadas") and not cu.is_outros("Outorga de Concessão")
    assert not cu.is_outros(None)
```

Em `tests/test_consistency_cross_period.py`, logo antes de `# ── main():`:

```python
def test_iter_pairs_baseline_e_contexto():
    dfp24 = _doc("DFP", "2024-12-31", "Penúltimo", "NA", "2023-12-31", BPA)
    pares = list(ccp.iter_pairs(_df(_itr1t24(), dfp24, _dfp23())))
    assert [(p["fonte_cmp"], p["data_cmp"]) for p, _, _ in pares] == [("ITR", "2024-03-31"), ("DFP", "2024-12-31")]
    par, ref, cmp = pares[0]
    assert par == {"cnpj_companhia": CNPJ, "tipo_doc": "BPA", "periodo_ini": "NA", "periodo_fim": "2023-12-31",
                   "fonte_ref": "DFP", "data_ref": "2023-12-31", "ordem_ref": "Último",
                   "fonte_cmp": "ITR", "data_cmp": "2024-03-31", "ordem_cmp": "Penúltimo"}
    assert set(ref["cd_conta"]) == set(BPA) and set(cmp["fonte"]) == {"ITR"}
    assert list(ccp.iter_pairs(pd.DataFrame())) == []
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_utils.py tests/test_consistency_cross_period.py -q -k "normalize or is_outros or iter_pairs" 2>&1 | tail -4
```

Expected: 3 failed (`AttributeError` em `normalize_text`, `is_outros`, `iter_pairs`).

- [ ] **Step 3: Implementar**

`consistency_utils.py` — imports (`import re`, `import unicodedata` junto aos demais da stdlib), `__all__` com `"normalize_text", "is_outros", "OUTROS_RE"`, e logo depois de `parse_hierarchy`:

```python
# ── Texto (Camadas 3, 4 e 5) ─────────────────────────────────────────────────
# "Outros"/"Outras"/"Outro"/"Demais" como palavra inteira sobre texto normalizado.
# `\boutr` do plano original casava "outorgadas" (148 linhas no BPP 2024).
OUTROS_RE = re.compile(r"\b(outr[oa]s?|demais)\b")


def normalize_text(s) -> str:
    """Minúsculas, sem acentos, só [a-z0-9 ], espaços colapsados; None/NaN → ''."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def is_outros(ds_conta) -> bool:
    return bool(OUTROS_RE.search(normalize_text(ds_conta)))
```

`check_cross_period.py` — substituir `check_cross_period` (mantendo `_doc_rows`) por:

```python
def iter_pairs(df: pd.DataFrame):
    """Gera (par, ref, cmp) para cada período e cada filing posterior ao baseline.

    par = {cnpj_companhia, tipo_doc, periodo_ini, periodo_fim,
           fonte_ref, data_ref, ordem_ref, fonte_cmp, data_cmp, ordem_cmp};
    ref/cmp = linhas do baseline (menor data_referencia) e do filing comparado
    nesse período. Usado pelas Camadas 2 e 3.
    Linhas com periodo_fim NULL são ignoradas (groupby descarta NaN na chave).
    """
    if df.empty:
        return
    for (cnpj, tipo_doc, p_ini, p_fim), grupo in df.groupby(GROUP_COLS, sort=True):
        docs = list(grupo[DOC_COLS].drop_duplicates().sort_values(DOC_COLS).itertuples(index=False))
        if len(docs) < 2:
            continue
        ref_doc = docs[0]
        ref = _doc_rows(grupo, ref_doc)
        for cmp_doc in docs[1:]:
            par = {
                "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
                "periodo_ini": p_ini, "periodo_fim": p_fim,
                "fonte_ref": ref_doc.fonte, "data_ref": ref_doc.data_referencia, "ordem_ref": ref_doc.ordem_exercicio,
                "fonte_cmp": cmp_doc.fonte, "data_cmp": cmp_doc.data_referencia, "ordem_cmp": cmp_doc.ordem_exercicio,
            }
            yield par, ref, _doc_rows(grupo, cmp_doc)


def check_cross_period(df: pd.DataFrame, tol_abs: float = 1000.0,
                       tol_rel: float = 0.01) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"pares": n, "pares_divergentes": m, "reapresentacao": k},
    contando pares (documento_ref, documento_cmp, período).
    """
    flags: list[dict] = []
    stats: dict = {}
    for par, ref, cmp in iter_pairs(df):
        tipo_doc = par["tipo_doc"]
        st = stats.setdefault(tipo_doc, {"pares": 0, "pares_divergentes": 0, "reapresentacao": 0})
        st["pares"] += 1
        linhas, resumo = compare_pair(ref, cmp, tipo_doc, tol_abs, tol_rel)
        if resumo["linhas_divergentes"] == 0:
            continue
        st["pares_divergentes"] += 1
        if resumo["classificacao"] == "reapresentacao":
            st["reapresentacao"] += 1
        contexto = {"layer": LAYER, "check_type": CHECK_TYPE, **par}
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

- [ ] **Step 4: Rodar e ver passar (a suíte inteira — a refatoração não pode mudar a Camada 2)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: 118 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/consistency_utils.py scripts/analysis/check_cross_period.py tests/test_consistency_utils.py tests/test_consistency_cross_period.py && git commit -q -m "refactor(analysis): iter_pairs na Camada 2; normalize_text e is_outros nos utils (Fase 3)" && git log --oneline -1
```

---

### Task 2: `check_granularity.py` — lógica pura + CLI

**Files:**
- Create: `scripts/analysis/check_granularity.py`
- Test: `tests/test_consistency_granularity.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
"""
Fase 3 da consistência financeira: Camada 3 (granularidade entre filings).
Lógica pura (DataFrame → flags) sem banco; main() ao final com banco em memória.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_granularity as ccg

CNPJ = "84.429.695/0001-11"
BASE = {"1": ("Ativo Total", 100e6), "1.01": ("Ativo Circulante", 60e6),
        "1.01.01": ("Caixa", 20e6), "1.01.02": ("Contas a Receber", 30e6), "1.01.03": ("Estoques", 10e6),
        "1.02": ("Ativo Não Circulante", 40e6)}


def _doc(contas, fonte="DFP", data_ref="2023-12-31", ordem="Último", p_ini="NA", p_fim="2023-12-31",
         tipo_doc="BPA", st="S"):
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": p_ini, "periodo_fim": p_fim,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": vl,
             "st_conta_fixa": (v[2] if len(v) > 2 else st)}
            for cd, v in contas.items() for ds, vl in [v[:2]]]


def _ref(contas=BASE):
    return _doc(contas)


def _cmp(contas):
    return _doc(contas, "ITR", "2024-03-31", "Penúltimo")


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


def _linhas(flags):
    return [f for f in flags if f["cd_conta"] is not None]


def _resumo(flags):
    r, = [f for f in flags if f["cd_conta"] is None]
    return r


def _classes(flags):
    return {(f["cd_conta"], f["classificacao"]) for f in _linhas(flags)}


def test_sem_exclusivos_nao_gera_flag():
    flags, stats = ccg.check_granularity(_df(_ref(), _cmp(BASE)))
    assert flags == []
    assert stats == {"BPA": {"pares": 1, "pares_com_exclusivos": 0, "renumerado": 0, "zero_padding": 0,
                             "reclassificado_em_outros": 0, "reclassificado_em_irmao": 0,
                             "divergencia_nao_explicada": 0}}
    assert ccg.check_granularity(pd.DataFrame()) == ([], {})


def test_renumerado_por_nome_ignora_acento_e_caixa():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("ESTOQUES", 11e6)
    flags, stats = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["cd_conta_pai"], f["classificacao"], f["severity"]) == ("1.01.03", "1.01", "renumerado", "info")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == (10e6, 11e6, 1e6)
    assert f["detalhe"] == {"casamento": "nome", "cd_ref": "1.01.03", "cd_cmp": "1.01.07"}
    assert (f["layer"], f["check_type"], f["fonte_cmp"], f["data_cmp"]) == (3, "granularity", "ITR", "2024-03-31")
    assert _resumo(flags)["classificacao"] == "renumerado"
    assert _resumo(flags)["detalhe"] == {"linhas_exclusivas_ref": 1, "linhas_exclusivas_cmp": 1, "filhos_de_pai_exclusivo": 0,
                                         "renumerado": 1, "zero_padding": 0, "reclassificado_em_outros": 0,
                                         "reclassificado_em_irmao": 0, "divergencia_nao_explicada": 0}
    assert stats["BPA"]["pares_com_exclusivos"] == 1 and stats["BPA"]["renumerado"] == 1


def test_nome_igual_com_st_conta_fixa_diferente_nao_casa():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("Estoques", 12e6, "N")
    cmp["1.01.01"] = ("Caixa", 18e6)                            # pai 1.01 continua 60e6
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    assert _classes(flags) == {("1.01.03", "reclassificado_em_irmao"), ("1.01.07", "reclassificado_em_irmao")}


def test_zero_padding_valor_pequeno_ou_nulo():
    cmp = dict(BASE, **{"1.01.04": ("Adiantamentos", 900.0), "1.01.05": ("Tributos a Recuperar", None)})
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    assert _classes(flags) == {("1.01.04", "zero_padding"), ("1.01.05", "zero_padding")}
    f = [x for x in _linhas(flags) if x["cd_conta"] == "1.01.04"][0]
    assert (f["valor_ref"], f["valor_cmp"], f["severity"]) == (None, 900.0, "info")
    assert f["detalhe"] == {"exclusivo_em": "cmp"}


def test_tres_linhas_finas_viram_uma_outras():
    ref = dict(BASE, **{"1.01.04": ("Adiantamentos", 2e6), "1.01.05": ("Tributos", 3e6), "1.01.06": ("Despesas Antecipadas", 5e6)})
    ref["1.01"] = ("Ativo Circulante", 70e6); ref["1"] = ("Ativo Total", 110e6)
    cmp = dict(BASE, **{"1.01.09": ("Outras Contas", 10e6)})
    cmp["1.01"] = ("Ativo Circulante", 70e6); cmp["1"] = ("Ativo Total", 110e6)
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert {c for _, c in _classes(flags)} == {"reclassificado_em_outros"}
    assert {cd for cd, _ in _classes(flags)} == {"1.01.04", "1.01.05", "1.01.06", "1.01.09"}
    f = [x for x in _linhas(flags) if x["cd_conta"] == "1.01.04"][0]
    assert f["severity"] == "warn"
    assert f["detalhe"] == {"exclusivo_em": "ref", "soma_exclusivos_ref": 10e6, "soma_exclusivos_cmp": 0.0,
                            "outros_ref": 0.0, "outros_cmp": 10e6, "cd_outros_ref": [], "cd_outros_cmp": ["1.01.09"]}
    assert _resumo(flags)["classificacao"] == "reclassificado_em_outros" and _resumo(flags)["severity"] == "warn"


def test_outros_comum_absorve_linha_removida():
    ref = dict(BASE, **{"1.01.09": ("Outros", 1e6)}); ref["1.01"] = ("Ativo Circulante", 61e6)
    cmp = dict(BASE, **{"1.01.09": ("Outros", 11e6)}); cmp.pop("1.01.03"); cmp["1.01"] = ("Ativo Circulante", 61e6)
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert _classes(flags) == {("1.01.03", "reclassificado_em_outros")}


def test_renumerado_por_valor_sem_outros():
    ref = {"6.03": ("Financiamento", -100e6), "6.03.08": ("Dividendos Pagos", -100e6)}
    cmp = {"6.03": ("Financiamento", -100e6), "6.03.07": ("Dividendos pagos e a pagar", -100e6)}
    flags, _ = ccg.check_granularity(_df(_doc(ref, tipo_doc="DFC_MI", p_ini="2023-01-01"),
                                         _doc(cmp, "ITR", "2024-03-31", "Penúltimo", "2023-01-01", tipo_doc="DFC_MI")))
    assert _classes(flags) == {("6.03.08", "renumerado"), ("6.03.07", "renumerado")}
    f = [x for x in _linhas(flags) if x["cd_conta"] == "6.03.07"][0]
    assert f["detalhe"] == {"exclusivo_em": "cmp", "casamento": "valor", "cd_ref": ["6.03.08"], "cd_cmp": ["6.03.07"]}
    assert (f["valor_ref"], f["valor_cmp"]) == (None, -100e6)


def test_reclassificado_em_irmao_pai_inalterado():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.01"] = ("Caixa", 30e6)     # Estoques sumiu, Caixa absorveu; 1.01 = 60e6
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01.03", "reclassificado_em_irmao", "warn")
    assert f["detalhe"] == {"exclusivo_em": "ref", "soma_exclusivos_ref": 10e6, "soma_exclusivos_cmp": 0.0,
                            "pai_ref": 60e6, "pai_cmp": 60e6,
                            "irmaos_alterados": [{"cd": "1.01.01", "ref": 20e6, "cmp": 30e6}]}


def test_divergencia_nao_explicada_pai_mudou():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01"] = ("Ativo Circulante", 50e6); cmp["1"] = ("Ativo Total", 90e6)
    flags, stats = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01.03", "divergencia_nao_explicada", "error")
    assert f["detalhe"] == {"exclusivo_em": "ref", "soma_exclusivos_ref": 10e6, "soma_exclusivos_cmp": 0.0,
                            "pai_ref": 60e6, "pai_cmp": 50e6}
    assert _resumo(flags)["severity"] == "error"
    assert stats["BPA"]["divergencia_nao_explicada"] == 1


def test_raiz_sem_pai_vai_para_nao_explicada():
    ref = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6)}
    cmp = {"3.01": ("Receita", 100e6)}
    flags, _ = ccg.check_granularity(_df(_doc(ref, tipo_doc="DRE", p_ini="2023-01-01"),
                                         _doc(cmp, "ITR", "2024-03-31", "Penúltimo", "2023-01-01", tipo_doc="DRE")))
    f, = _linhas(flags)
    assert (f["cd_conta"], f["cd_conta_pai"], f["classificacao"]) == ("3.02", "3", "divergencia_nao_explicada")
    assert f["detalhe"]["pai_ref"] is None and f["detalhe"]["pai_cmp"] is None


def test_opcoes_outorgadas_nao_e_outros():
    ref = dict(BASE, **{"1.01.09": ("Outros", 5e6)}); ref["1.01"] = ("Ativo Circulante", 65e6)
    cmp = dict(ref, **{"1.01.08": ("Opções Outorgadas", 2e6), "1.01.01": ("Caixa", 18e6)})   # 1.01 continua 65e6
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert _classes(flags) == {("1.01.08", "reclassificado_em_irmao")}


def test_filhos_de_pai_exclusivo_nao_geram_flag():
    cmp = dict(BASE, **{"1.02.05": ("Direito de Uso", 5e6), "1.02.05.01": ("Imóveis", 5e6), "1.02.01": ("Realizável LP", -5e6)})
    ref = dict(BASE, **{"1.02.01": ("Realizável LP", 0.0)})
    flags, _ = ccg.check_granularity(_df(_ref(ref), _cmp(cmp)))
    assert _classes(flags) == {("1.02.05", "reclassificado_em_irmao")}
    assert _resumo(flags)["detalhe"]["filhos_de_pai_exclusivo"] == 1
    assert _resumo(flags)["detalhe"]["linhas_exclusivas_cmp"] == 2


def test_tolerancia_no_balanco():
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("Inventário", 10e6 + 50e3)   # 0,5% < 1%
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)))
    assert {c for _, c in _classes(flags)} == {"renumerado"}
    flags, _ = ccg.check_granularity(_df(_ref(), _cmp(cmp)), tol_rel=0.001)
    assert {c for _, c in _classes(flags)} == {"reclassificado_em_irmao"}     # 50e3 > 0,1%: não casa por valor; pai inalterado


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db_com_docs():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO companies (cnpj, ticker, nome_cvm) VALUES (?, 'WEGE3', 'WEG')", (CNPJ,))
    cmp = dict(BASE); cmp.pop("1.01.03"); cmp["1.01.07"] = ("ESTOQUES", 10e6)
    rows = _ref() + _cmp(cmp)
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
    monkeypatch.setattr(ccg, "get_db", lambda: conn)
    run1 = ccg.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT cd_conta, classificacao, severity FROM consistency_flags WHERE run_id = ? ORDER BY cd_conta",
                       (run1,)).fetchall()
    assert got == [(None, "renumerado", "info"), ("1.01.03", "renumerado", "info")]
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, finished_at "
                       "FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (3, "granularity", f"cnpj={CNPJ}", 1, 2) and run[5] is not None
    run2 = ccg.main(["--cnpj", CNPJ, "--tipo-doc", "BPA"])
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags").fetchone() == (2, 1)
    assert conn.execute("SELECT DISTINCT run_id FROM consistency_flags").fetchone()[0] == run2
    out = capsys.readouterr().out
    assert "BPA" in out and "pares=1" in out and "com_exclusivos=1" in out and "renumerado=1" in out


def test_main_full_e_exigencia_de_cnpj(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(ccg, "get_db", lambda: conn)
    run_id = ccg.main(["--full"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    import pytest
    with pytest.raises(SystemExit):
        ccg.main([])
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_granularity.py -q 2>&1 | tail -3
```

Expected: erro de coleta `ModuleNotFoundError: No module named 'check_granularity'`.

- [ ] **Step 3: Criar `scripts/analysis/check_granularity.py`**

```python
"""
Camada 3 — granularidade entre filings (check_type = 'granularity').

Reaproveita os pares da Camada 2 (mesmo período, baseline × filing posterior;
check_cross_period.iter_pairs) e explica as linhas que existem só num dos lados
("exclusivas"), pai a pai, nesta ordem:
  1. nome   — mesmo ds_conta normalizado e mesmo st_conta_fixa dos dois lados
              → 'renumerado' (info; detalhe.casamento = 'nome', cd_ref, cd_cmp)
  2. zero   — |valor| < tol_abs (NULL = 0)            → 'zero_padding' (info)
  3. Outros — Σ exclusivas_ref − Σ exclusivas_cmp ≈ Σ Outros_cmp − Σ Outros_ref,
              contando as linhas "Outros"/"Demais" (consistency_utils.is_outros)
              entre os filhos do pai nos dois lados, comuns ou exclusivas
              → 'reclassificado_em_outros' (warn)
  4. valor  — exclusivas nos dois lados com Σ ref ≈ Σ cmp
              → 'renumerado' (info; detalhe.casamento = 'valor')
  5. irmão  — pai comum com pai_ref ≈ pai_cmp: o valor foi absorvido por um irmão
              nomeado → 'reclassificado_em_irmao' (warn; detalhe.irmaos_alterados)
  6. senão  — o valor saiu do pai (mudou de pai ou faz parte de uma reapresentação)
              → 'divergencia_nao_explicada' (error; detalhe.pai_ref/pai_cmp)
"≈" é |a − b| ≤ max(tol_abs, tol_rel × max(|a|, |b|)). Exclusivas cujo pai também é
exclusivo não geram flag (o pai é resolvido um nível acima); pai ausente dos dois
lados (ex: '3' na DRE) conta como raiz.

Saída: uma flag por linha exclusiva (valor_ref OU valor_cmp preenchido,
detalhe.exclusivo_em ∈ {'ref','cmp'}), ou por par casado por nome (cd_conta =
cd_ref, valor_ref e valor_cmp), mais uma flag-resumo por par com exclusivas
(cd_conta NULL; classificacao = classe mais grave; detalhe = contagens).
Flags anteriores do mesmo (cnpj[, tipo_doc]) são apagadas antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) depois da Camada 2. À mão
(na pasta scripts/analysis, .venv ativo):
  python check_granularity.py --cnpj 84.429.695/0001-11
  python check_granularity.py --cnpj 84.429.695/0001-11 --tipo-doc BPA --desde 2023
  python check_granularity.py --full             # base inteira (~145 empresas, ~2 min)
"""
import pandas as pd

from check_cross_period import iter_pairs
from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, is_outros, latest_rows,
                               new_run, normalize_text, parent_code, tolerancia, write_flags)

LAYER = 3
CHECK_TYPE = "granularity"
SEVERITY = {"renumerado": "info", "zero_padding": "info", "reclassificado_em_outros": "warn",
            "reclassificado_em_irmao": "warn", "divergencia_nao_explicada": "error"}
ORDEM_GRAVIDADE = ["divergencia_nao_explicada", "reclassificado_em_irmao", "reclassificado_em_outros",
                   "renumerado", "zero_padding"]
RESUMO_KEYS = ["linhas_exclusivas_ref", "linhas_exclusivas_cmp", "filhos_de_pai_exclusivo", *SEVERITY]


def _valor(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def _st(row):
    st = row.st_conta_fixa
    return None if st is None or (isinstance(st, float) and pd.isna(st)) else st


def _bate(a: float, b: float, tol_abs: float, tol_rel: float) -> bool:
    return abs(a - b) <= tolerancia(max(abs(a), abs(b)), tol_abs, tol_rel)


def _flag_linha(lado: str, cd: str, row, pai, classe: str, detalhe: dict) -> dict:
    val = _valor(row.vl_conta)
    return {
        "cd_conta": cd, "cd_conta_pai": pai, "ds_conta": row.ds_conta,
        "valor_ref": val if lado == "ref" else None,
        "valor_cmp": val if lado == "cmp" else None,
        "classificacao": classe, "severity": SEVERITY[classe],
        "detalhe": {"exclusivo_em": lado, **detalhe},
    }


def _resolver_pai(pai, ex_ref: list[str], ex_cmp: list[str], R: dict, C: dict,
                  tol_abs: float, tol_rel: float) -> list[dict]:
    """Exclusivas de UM pai (códigos em ex_ref só existem em R; ex_cmp só em C)."""
    flags: list[dict] = []

    # 1. nome (+ st_conta_fixa)
    nomes_ref: dict = {}
    nomes_cmp: dict = {}
    for cd in ex_ref:
        nomes_ref.setdefault((normalize_text(R[cd].ds_conta), _st(R[cd])), []).append(cd)
    for cd in ex_cmp:
        nomes_cmp.setdefault((normalize_text(C[cd].ds_conta), _st(C[cd])), []).append(cd)
    rest_ref: list[str] = []
    rest_cmp: list[str] = []
    for chave in list(nomes_ref) + [k for k in nomes_cmp if k not in nomes_ref]:
        a, b = nomes_ref.get(chave, []), nomes_cmp.get(chave, [])
        for cd_r, cd_c in zip(a, b):
            vr, vc = _valor(R[cd_r].vl_conta), _valor(C[cd_c].vl_conta)
            flags.append({
                "cd_conta": cd_r, "cd_conta_pai": pai, "ds_conta": R[cd_r].ds_conta,
                "valor_ref": vr, "valor_cmp": vc, "diff_abs": vc - vr,
                "diff_rel": (vc - vr) / abs(vr) if vr else None,
                "classificacao": "renumerado", "severity": SEVERITY["renumerado"],
                "detalhe": {"casamento": "nome", "cd_ref": cd_r, "cd_cmp": cd_c},
            })
        rest_ref += a[len(b):]
        rest_cmp += b[len(a):]

    # 2. zero
    restantes: list[tuple[str, str, object]] = []
    for lado, cds, docs in (("ref", rest_ref, R), ("cmp", rest_cmp, C)):
        for cd in cds:
            if abs(_valor(docs[cd].vl_conta)) < tol_abs:
                flags.append(_flag_linha(lado, cd, docs[cd], pai, "zero_padding", {}))
            else:
                restantes.append((lado, cd, docs[cd]))
    if not restantes:
        return flags

    soma_ref = sum(_valor(row.vl_conta) for lado, _, row in restantes if lado == "ref")
    soma_cmp = sum(_valor(row.vl_conta) for lado, _, row in restantes if lado == "cmp")
    extra = {"soma_exclusivos_ref": soma_ref, "soma_exclusivos_cmp": soma_cmp}

    # 3. Outros (linhas "Outros" dos dois lados, comuns ou exclusivas; ausente = 0)
    outros_ref = [cd for cd in R if parent_code(cd) == pai and is_outros(R[cd].ds_conta)]
    outros_cmp = [cd for cd in C if parent_code(cd) == pai and is_outros(C[cd].ds_conta)]
    if outros_ref or outros_cmp:
        o_ref = sum(_valor(R[cd].vl_conta) for cd in outros_ref)
        o_cmp = sum(_valor(C[cd].vl_conta) for cd in outros_cmp)
        nao_outros_ref = sum(_valor(row.vl_conta) for lado, cd, row in restantes if lado == "ref" and cd not in outros_ref)
        nao_outros_cmp = sum(_valor(row.vl_conta) for lado, cd, row in restantes if lado == "cmp" and cd not in outros_cmp)
        if _bate(nao_outros_ref - nao_outros_cmp, o_cmp - o_ref, tol_abs, tol_rel):
            det = {"soma_exclusivos_ref": nao_outros_ref, "soma_exclusivos_cmp": nao_outros_cmp,
                   "outros_ref": o_ref, "outros_cmp": o_cmp,
                   "cd_outros_ref": outros_ref, "cd_outros_cmp": outros_cmp}
            flags += [_flag_linha(lado, cd, row, pai, "reclassificado_em_outros", det) for lado, cd, row in restantes]
            return flags

    # 4. valor
    cds_ref = [cd for lado, cd, _ in restantes if lado == "ref"]
    cds_cmp = [cd for lado, cd, _ in restantes if lado == "cmp"]
    if cds_ref and cds_cmp and _bate(soma_ref, soma_cmp, tol_abs, tol_rel):
        det = {"casamento": "valor", "cd_ref": cds_ref, "cd_cmp": cds_cmp}
        flags += [_flag_linha(lado, cd, row, pai, "renumerado", det) for lado, cd, row in restantes]
        return flags

    # 5. irmão
    pai_ref = pai_cmp = None
    if pai is not None and pai in R and pai in C:
        pai_ref, pai_cmp = _valor(R[pai].vl_conta), _valor(C[pai].vl_conta)
        if _bate(pai_ref, pai_cmp, tol_abs, tol_rel):
            alterados = []
            for cd in R:
                if parent_code(cd) != pai or cd not in C:
                    continue
                vr, vc = _valor(R[cd].vl_conta), _valor(C[cd].vl_conta)
                if abs(vc - vr) > tolerancia(vr, tol_abs, tol_rel):
                    alterados.append({"cd": cd, "ref": vr, "cmp": vc})
            det = {**extra, "pai_ref": pai_ref, "pai_cmp": pai_cmp, "irmaos_alterados": alterados[:10]}
            flags += [_flag_linha(lado, cd, row, pai, "reclassificado_em_irmao", det) for lado, cd, row in restantes]
            return flags

    # 6. não explicada
    det = {**extra, "pai_ref": pai_ref, "pai_cmp": pai_cmp}
    flags += [_flag_linha(lado, cd, row, pai, "divergencia_nao_explicada", det) for lado, cd, row in restantes]
    return flags


def compare_granularity(ref: pd.DataFrame, cmp: pd.DataFrame,
                        tol_abs: float = 1000.0, tol_rel: float = 0.01) -> tuple[list[dict], dict]:
    """Linhas de UM período em dois documentos. Retorna (flags_de_linha, resumo)."""
    R = {r.cd_conta: r for r in ref.itertuples(index=False)}
    C = {r.cd_conta: r for r in cmp.itertuples(index=False)}
    ex_ref = [cd for cd in R if cd not in C]
    ex_cmp = [cd for cd in C if cd not in R]
    resumo = {k: 0 for k in RESUMO_KEYS}
    resumo["linhas_exclusivas_ref"], resumo["linhas_exclusivas_cmp"] = len(ex_ref), len(ex_cmp)
    flags: list[dict] = []
    if not ex_ref and not ex_cmp:
        return flags, resumo
    exclusivos = set(ex_ref) | set(ex_cmp)
    por_pai: dict = {}
    for cd in ex_ref:
        por_pai.setdefault(parent_code(cd), ([], []))[0].append(cd)
    for cd in ex_cmp:
        por_pai.setdefault(parent_code(cd), ([], []))[1].append(cd)
    for pai, (er, ec) in por_pai.items():
        if pai is not None and pai in exclusivos:
            resumo["filhos_de_pai_exclusivo"] += len(er) + len(ec)
            continue
        flags.extend(_resolver_pai(pai, er, ec, R, C, tol_abs, tol_rel))
    for f in flags:
        resumo[f["classificacao"]] += 1
    return flags, resumo


def check_granularity(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"pares": n, "pares_com_exclusivos": m, <classe>: n_flags_de_linha}.
    """
    flags: list[dict] = []
    stats: dict = {}
    for par, ref, cmp in iter_pairs(df):
        tipo_doc = par["tipo_doc"]
        st = stats.setdefault(tipo_doc, {"pares": 0, "pares_com_exclusivos": 0, **{c: 0 for c in SEVERITY}})
        st["pares"] += 1
        linhas, resumo = compare_granularity(ref, cmp, tol_abs, tol_rel)
        if not linhas:
            continue
        st["pares_com_exclusivos"] += 1
        for c in SEVERITY:
            st[c] += resumo[c]
        contexto = {"layer": LAYER, "check_type": CHECK_TYPE, **par}
        flags.extend({**contexto, **linha} for linha in linhas)
        classe = next(c for c in ORDEM_GRAVIDADE if resumo[c])
        flags.append({**contexto, "cd_conta": None, "classificacao": classe, "severity": SEVERITY[classe],
                      "detalhe": {k: resumo[k] for k in RESUMO_KEYS}})
    return flags, stats


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
    """Roda a Camada 3 e devolve o run_id. `argv=None` lê sys.argv."""
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
        flags, stats = check_granularity(df, args.tol_abs, args.tol_rel)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_flags(conn, run_id, flags)
        pares = sum(s["pares"] for s in stats.values())
        total_checked += pares
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {pares} pares, {n} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (pares = documento_ref × documento_cmp × período):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        classes = " ".join(f"{c}={s[c]}" for c in SEVERITY)
        print(f"  {tipo:7s} pares={s['pares']} com_exclusivos={s['pares_com_exclusivos']} {classes}")
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_granularity.py -q 2>&1 | tail -3
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/check_granularity.py tests/test_consistency_granularity.py && git commit -q -m "feat(analysis): Camada 3 — check_granularity (renumerado, zero_padding, Outros, irmão, não explicada)" && git log --oneline -1
```

---

### Task 3: `run_all.py` + `update_weekly.sh`

- [ ] **Step 1: Registrar a camada 3 em `run_all.py`**

```python
import check_cross_period
import check_granularity
import check_hierarchy_sums

LAYERS = {
    1: check_hierarchy_sums.main,
    2: check_cross_period.main,
    3: check_granularity.main,
}
```

Docstring: `(3 = granularidade, 5 = trilha temporal, 6 = desacúmulo)` → `(5 = trilha temporal, 6 = desacúmulo)`; `chama `run_all.py --layer 1 --full` e `--layer 2 --full`` → `chama `run_all.py --layer N --full` para N = 1, 2, 3`.

- [ ] **Step 2: Passo `consistency_l3` no `update_weekly.sh`**

Depois de `run_step "consistency_l2" ...`, acrescentar `run_step "consistency_l3" ../analysis/run_all.py --layer 3 --full`; no comentário do bloco, `Camada 1 (...) e Camada 2 (reapresentações entre filings)` → `Camada 1 (...), Camada 2 (reapresentações entre filings) e Camada 3 (linhas sem par entre filings)`; no cabeçalho, `(Camadas 1 e 2)` → `(Camadas 1 a 3)`.

- [ ] **Step 3: Conferir**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && ../../.venv/bin/python run_all.py --help | grep dispon && bash -n ../update_weekly.sh && echo shell-ok && cd ../.. && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -1
```

Expected: `disponíveis: 1,2,3`; `shell-ok`; 133 passed.

- [ ] **Step 4: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/run_all.py scripts/update_weekly.sh && git commit -q -m "feat(analysis): run_all --layer 3; Camada 3 no update_weekly.sh" && git log --oneline -1
```

---

### Task 4: Fumaça no banco real — WEGE3

- [ ] **Step 1: Rodar, inspecionar e conferir idempotência + Camadas 1/2 intactas**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -c "
import sqlite3; c=sqlite3.connect('cvm_research.db')
print('L1/L2 WEG antes:', c.execute(\"SELECT layer, COUNT(*) FROM consistency_flags WHERE cnpj_companhia='84.429.695/0001-11' GROUP BY 1\").fetchall())" && cd scripts/analysis && ../../.venv/bin/python run_all.py --layer 3 --cnpj 84.429.695/0001-11 | tail -8 && ../../.venv/bin/python run_all.py --layer 3 --cnpj 84.429.695/0001-11 | tail -1 && cd ../.. && .venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("cvm_research.db"); W = "84.429.695/0001-11"
print("L1/L2/L3 WEG depois:", c.execute("SELECT layer, COUNT(*), COUNT(DISTINCT run_id) FROM consistency_flags WHERE cnpj_companhia=? GROUP BY 1", (W,)).fetchall())
print("L3 por classe:", c.execute("SELECT tipo_doc, classificacao, COUNT(*) FROM consistency_flags WHERE layer=3 AND cnpj_companhia=? AND cd_conta IS NOT NULL GROUP BY 1,2 ORDER BY 1,2", (W,)).fetchall())
for r in c.execute("SELECT tipo_doc, cd_conta, ds_conta, periodo_fim, fonte_cmp, data_cmp, classificacao, valor_ref, valor_cmp, detalhe FROM consistency_flags WHERE layer=3 AND cnpj_companhia=? AND cd_conta IS NOT NULL ORDER BY severity DESC, data_cmp DESC LIMIT 6", (W,)): print(r)
EOF
```

Expected: contagens de `layer=1` e `layer=2` iguais antes e depois; `layer=3` com 1 `run_id` distinto após duas execuções; classes plausíveis (zero_padding dominante).

---

### Task 5: Execução completa e verificação

- [ ] **Step 1: Rodar a base inteira e medir**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && time ../../.venv/bin/python run_all.py --layer 3 --full 2>&1 | tail -9 && cd ../.. && .venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("cvm_research.db")
print("run:", c.execute("SELECT run_id, total_checked, total_flagged, started_at, finished_at FROM consistency_runs WHERE layer=3 ORDER BY started_at DESC LIMIT 1").fetchone())
print("linhas por classe:", c.execute("SELECT classificacao, COUNT(*) FROM consistency_flags WHERE layer=3 AND cd_conta IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("resumos por classe dominante:", c.execute("SELECT classificacao, COUNT(*) FROM consistency_flags WHERE layer=3 AND cd_conta IS NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("BPA DFP(Y) x ITR 1T(Y+1) com exclusivos:", c.execute("""SELECT COUNT(*), SUM(classificacao='divergencia_nao_explicada') FROM consistency_flags
WHERE layer=3 AND cd_conta IS NULL AND tipo_doc='BPA' AND fonte_ref='DFP' AND fonte_cmp='ITR' AND substr(data_cmp,6)='03-31'""").fetchone())
print("casamento:", c.execute("SELECT json_extract(detalhe,'$.casamento'), COUNT(*) FROM consistency_flags WHERE layer=3 AND classificacao='renumerado' GROUP BY 1").fetchall())
print("nao_explicada por tipo:", c.execute("SELECT tipo_doc, COUNT(*) FROM consistency_flags WHERE layer=3 AND classificacao='divergencia_nao_explicada' AND cd_conta IS NOT NULL GROUP BY 1").fetchall())
EOF
```

Expected (protótipo de 2026-09-18): `zero_padding` ≈ 33 mil, `reclassificado_em_irmao` ≈ 10 mil, `divergencia_nao_explicada` ≈ 11 mil, `renumerado` ≈ 700 (≈ 570 por nome), `reclassificado_em_outros` entre 500 e 4 mil; 620 pares BPA DFP × ITR 1T com exclusivos. Se `divergencia_nao_explicada` passar de 60% das linhas, o casamento por nome ou o balanço com "Outros" está quebrado.

- [ ] **Step 2: Registrar no plano-mãe** (ponteiro no topo da Fase 3 + linha "Medido em 2026-09-18" na "Verificação da Fase 3") e commit:

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md && git commit -q -m "docs(plano): numeros medidos da Camada 3 na base; ponteiro para o plano da Fase 3" && git log --oneline -1
```

---

### Task 6: Documentação

- [ ] **Step 1: `CLAUDE.md`** — na subseção `consistency_flags`: `As Camadas 1 e 2 rodam` → `As Camadas 1, 2 e 3 rodam`; no bullet da Camada 2 `Linha que existe só num dos filings **não** gera flag (Camada 3, futura); só entra nas contagens` → `Linha que existe só num dos filings **não** gera flag aqui (é a Camada 3); só entra nas contagens`; e depois do bloco da Camada 2 (antes de `Para rodar: ... --layer 2`) inserir:

```markdown
**Camada 3 (`layer = 3`, `check_type = 'granularity'`)** — nos mesmos pares da Camada 2, explica as linhas que existem
só num dos filings (`valor_ref` **ou** `valor_cmp` preenchido; `detalhe.exclusivo_em`), pai a pai, nesta ordem:
- `renumerado` (`info`): mesmo nome normalizado e mesmo `st_conta_fixa` em código diferente (`detalhe.casamento = 'nome'`,
  `cd_ref`/`cd_cmp`; uma flag por par casado, `cd_conta = cd_ref`), ou exclusivas dos dois lados com a mesma soma (`'valor'`).
- `zero_padding` (`info`): |valor| < R$ 1.000 — conta padrão publicada vazia.
- `reclassificado_em_outros` (`warn`): a soma das exclusivas fecha com o delta das linhas "Outros"/"Demais" do pai.
- `reclassificado_em_irmao` (`warn`): o pai não mudou; o valor foi absorvido por um irmão nomeado (`detalhe.irmaos_alterados`).
- `divergencia_nao_explicada` (`error`): o valor saiu do pai (`detalhe.pai_ref`/`pai_cmp`) — mudou de pai ou é parte de
  uma reapresentação (conferir a Camada 2 do mesmo par).
Exclusivas cujo pai também é exclusivo não geram flag (só `detalhe.filhos_de_pai_exclusivo` no resumo do par).
```

E a linha `Para rodar: `cd scripts/analysis && python run_all.py --layer 2 --cnpj <CNPJ>` (ou `--full` para a base).` → `Para rodar: `cd scripts/analysis && python run_all.py --layer 2,3 --cnpj <CNPJ>` (ou `--full` para a base).`

Query padrão, depois da query da Camada 1:

```markdown
### Linhas que existem só num dos filings (Camada 3)
```sql
-- Por que a conta X sumiu (ou apareceu) entre o DFP e o ITR seguinte?
SELECT tipo_doc, periodo_fim, fonte_cmp || ' ' || data_cmp AS comparado,
       cd_conta, ds_conta, classificacao, severity,
       valor_ref, valor_cmp,
       json_extract(detalhe, '$.exclusivo_em') AS exclusivo_em,
       json_extract(detalhe, '$.casamento')    AS casamento,
       json_extract(detalhe, '$.cd_cmp')       AS cd_cmp
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 3 AND cd_conta IS NOT NULL
  AND classificacao <> 'zero_padding'
ORDER BY periodo_fim DESC, severity DESC, cd_conta;
```
`zero_padding` é ruído estrutural (conta padrão vazia) e pode ser filtrado; `renumerado` diz qual código usar no outro filing.
```

Item 10 no "Comportamento esperado ao pesquisar" (após o 9):

```markdown
10. **Quando uma conta "some" entre dois filings** (ex: existia no DFP, não está no ITR seguinte): consulte a Camada 3
    para o par. `renumerado` dá o novo código; `reclassificado_em_outros`/`reclassificado_em_irmao` dizem onde o valor
    foi parar; `divergencia_nao_explicada` exige olhar a Camada 2 do mesmo par (reapresentação) antes de concluir.
```

- [ ] **Step 2: `README.md`** — árvore (`check_granularity.py # Camada 3: linhas sem par entre filings (renumeração, Outros, irmão)` depois de `check_cross_period.py`), `As Camadas 1 e 2 rodam` → `As Camadas 1, 2 e 3 rodam`, exemplo `--layer 1,2` → `--layer 1,2,3`, e linha na tabela depois da Camada 2:

```markdown
| 3 | `check_granularity.py` | Linhas que existem só num dos filings do par: `renumerado` (mesmo nome ou mesmo valor em outro código), `zero_padding`, `reclassificado_em_outros`, `reclassificado_em_irmao` (pai inalterado), `divergencia_nao_explicada`. |
```

- [ ] **Step 3: `scripts/mcp/cvm_mcp.py`** — na docstring, depois de `layer=2 cross_period: reapresentacao/reclassificacao entre filings;` acrescentar `layer=3 granularity: renumerado/zero_padding/reclassificado_em_outros/reclassificado_em_irmao/divergencia_nao_explicada para linhas só num dos filings;`.

- [ ] **Step 4: Conferir e commitar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -c "import ast; ast.parse(open('scripts/mcp/cvm_mcp.py').read()); print('mcp ok')" && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -1 && git add CLAUDE.md README.md scripts/mcp/cvm_mcp.py && git commit -q -m "docs: Camada 3 (granularity) no CLAUDE.md, README e docstring do MCP" && git log --oneline -1
```

---

## Verificação geral da Fase 3

- `pytest tests/` verde, sem tocar `cvm_research.db`; testes da Camada 2 inalterados após a refatoração de `iter_pairs`.
- `run_all.py --layer 3 --full` executado; números registrados no plano-mãe.
- Flags das Camadas 1 e 2 intactas após rodar a Camada 3; rerun substitui em vez de somar.
- `update_weekly.sh` passa `bash -n`; passos `consistency_l1/l2/l3` independentes.
