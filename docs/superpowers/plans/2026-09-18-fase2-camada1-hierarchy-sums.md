# Fase 2 — Camada 1 (soma hierárquica intra-documento) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Expande a seção "Fase 2" do plano-mãe `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` em tarefas com código, seguindo o precedente da Fase 1 (`2026-09-17-fase1-camada2-cross-period.md`). Pré-requisito: Fase 1 aplicada (tabelas `consistency_runs`/`consistency_flags` e `scripts/analysis/consistency_utils.py` existem; confirmado em 2026-09-18 no `main`, commit `83cdb57`).

**Goal:** Criar a Camada 1, que verifica, dentro de cada documento, se cada conta-pai é igual à soma dos filhos diretos (com as exceções `6.05` = saldo final − inicial e `3.99` ignorado) e se as fórmulas fixas de nível 2 da DRE e da DFC fecham, classificando cada falha como `nao_detalhado` (info), `pai_vazio` (warn), `divergencia` (error) ou `divergencia_formula` (error).

**Architecture:** Mesmo desenho da Camada 2: `check_hierarchy_sums.py` tem a lógica pura em funções testáveis com `DataFrame` (`check_document` para um documento×ordem×período, `check_hierarchy_sums` para a saída de `latest_rows`) mais um `main()` que percorre a base empresa a empresa, apaga as flags anteriores do escopo e grava as novas. `consistency_utils.py` ganha `parse_hierarchy`, as tabelas `EXCECOES_SOMA`/`FORMULAS_NIVEL2` e `cnpjs_financeiros` (as fórmulas de nível 2 não valem para o plano COSIF). A Camada 1 é o teste de regressão da ingestão, por isso entra no `update_weekly.sh` ao lado da Camada 2.

**Tech Stack:** Python 3.14 (`.venv`), `pandas` 2.2, `numpy`, `sqlite3` 3.50, `pytest` 8.3.

---

## Decisões de desenho verificadas contra o banco (2026-09-18)

| Ponto | O que a base mostra | Decisão |
|---|---|---|
| Formato de `cd_conta` | 0 linhas com `length(cd_conta) % 3 <> 1` (em 4,7 M). | `parse_hierarchy` usa `parent_code` (`rsplit('.', 1)`); pai de `X.YY.ZZ` é `X.YY`. |
| Nível 1 | Só BPA (`1`) e BPP (`2`) têm conta de nível 1; DRE/DFC_MI/DVA começam em `3.01`/`6.01`/`7.01`. | Só pais **presentes** no documento são checados; filho sem pai no documento não é flag (senão toda DRE geraria `pai_vazio` para o inexistente `3`). |
| Exceção `6.05` | Filhos são exatamente `6.05.01` "Saldo Inicial" e `6.05.02` "Saldo Final" (14.084 docs cada). | Regra `saldo`: `6.05 = 6.05.02 − 6.05.01`. |
| Exceção `3.99` | `3.99` "Lucro por Ação" com filhos `3.99.01`/`3.99.02` e netos ON/PN/PNA/PNB. | Regra `skip`: `3.99` e todos os descendentes ficam fora. |
| Fórmulas de nível 2 | DRE `3.01`…`3.11` e DFC `6.01`…`6.05` têm os nomes padrão da CVM em ~3.500 DFPs cada. | `FORMULAS_NIVEL2` exatamente como no plano-mãe; alvo ausente do documento → fórmula pulada; termo ausente conta como 0. |
| Setor financeiro | `companies.setor = 'Financeiro'` em 10 empresas (plano COSIF: nível 2 diverge do padrão). | `cnpjs_financeiros(conn)`; para elas `formulas=False` (a soma hierárquica continua valendo). |
| Unidade de verificação | Um ITR de 2T/3T tem trimestre e acumulado no mesmo documento e ordem (`dt_ini_exerc` distinto); todo documento tem `Último` e `Penúltimo`. | Grupo = `(cnpj, tipo_doc, fonte, data_referencia, ordem_exercicio, periodo_ini, periodo_fim)`. Penúltimo também é checado (é o valor que a Camada 2 usa como `cmp`). |
| Onde gravar o documento na flag | `consistency_flags` tem `fonte_ref/data_ref/ordem_ref` (baseline) e `*_cmp`. | Camada 1 preenche só `*_ref` com o documento; `*_cmp` ficam NULL. `valor_ref` = pai, `valor_cmp` = soma dos filhos (ou saldo, ou soma da fórmula), `diff_abs = valor_cmp − valor_ref`. |
| Idempotência | `clear_flags(conn, layer, check_type, cnpj[, tipo_doc])` já existe. | `check_type = 'hierarchy_sum'`, mesma limpeza por escopo antes de gravar. |

## Estrutura de arquivos

- **Modify:** `scripts/analysis/consistency_utils.py` — `parse_hierarchy`, `EXCECOES_SOMA`, `FORMULAS_NIVEL2`, `SETOR_FINANCEIRO`, `cnpjs_financeiros`; `__all__` atualizado.
- **Create:** `scripts/analysis/check_hierarchy_sums.py` — `check_document` (um documento×ordem×período), `check_hierarchy_sums` (um `DataFrame` de `latest_rows` → flags + stats), `main` (CLI, loop por CNPJ).
- **Modify:** `scripts/analysis/run_all.py` — registra a camada 1.
- **Modify:** `scripts/update_weekly.sh` — passo `consistency_l1` antes de `consistency_l2`.
- **Modify:** `tests/test_consistency_utils.py` — testes de `parse_hierarchy` e `cnpjs_financeiros`.
- **Create:** `tests/test_consistency_hierarchy.py` — lógica pura + `main()` com banco em memória.
- **Modify:** `CLAUDE.md` (subseção `consistency_flags`: Camada 1 + query padrão), `README.md` (árvore + tabela de camadas), `scripts/mcp/cvm_mcp.py` (docstring de `query`), plano-mãe (ponteiro + números medidos).

---

### Task 0: Branch de trabalho

**Files:** nenhum.

- [x] **Step 1: Criar o branch a partir de `main` limpo**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git status --short && git checkout -b fase-2-camada-1
```

Expected: `git status --short` vazio; `Switched to a new branch 'fase-2-camada-1'`.

---

### Task 1: `consistency_utils.py` — `parse_hierarchy`, exceções, fórmulas e setor financeiro

**Files:**
- Modify: `scripts/analysis/consistency_utils.py`
- Test: `tests/test_consistency_utils.py`

- [x] **Step 1: Escrever os testes que falham**

Acrescentar ao final da seção `# ── tolerancia / parent_code / total_codes` de `tests/test_consistency_utils.py`:

```python
# ── parse_hierarchy / exceções / fórmulas (Fase 2) ───────────────────────────

def test_parse_hierarchy_filhos_diretos_por_pai_presente():
    arvore = cu.parse_hierarchy(["1", "1.01", "1.01.01", "1.01.02", "1.02"])
    assert arvore == {"1": ["1.01", "1.02"], "1.01": ["1.01.01", "1.01.02"]}


def test_parse_hierarchy_ignora_pai_ausente_e_duplicatas():
    # DRE não tem conta "3": 3.01 não tem pai no documento, mas 3.01.01 tem
    assert cu.parse_hierarchy(["3.01", "3.01.01", "3.01.01", "3.02"]) == {"3.01": ["3.01.01"]}
    assert cu.parse_hierarchy([]) == {}
    assert cu.parse_hierarchy(pd.Series(["2", "2.01"])) == {"2": ["2.01"]}


def test_excecoes_e_formulas_fixas():
    assert cu.EXCECOES_SOMA == {("DFC_MI", "6.05"): "saldo", ("DRE", "3.99"): "skip"}
    assert [alvo for alvo, _ in cu.FORMULAS_NIVEL2["DRE"]] == ["3.03", "3.05", "3.07", "3.09", "3.11"]
    assert cu.FORMULAS_NIVEL2["DFC_MI"] == [("6.05", ["6.01", "6.02", "6.03", "6.04"])]
    assert "BPA" not in cu.FORMULAS_NIVEL2


def test_cnpjs_financeiros():
    conn = _db()
    conn.executemany("INSERT INTO companies (cnpj, ticker, nome_cvm, setor) VALUES (?,?,?,?)", [
        (CNPJ, "WEGE3", "WEG", "Industrial"),
        ("60.746.948/0001-12", "BBDC4", "BRADESCO", "Financeiro"),
        ("00.000.000/0001-91", "BBAS3", "BB", "Financeiro"),
    ])
    assert cu.cnpjs_financeiros(conn) == {"60.746.948/0001-12", "00.000.000/0001-91"}
```

- [x] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_utils.py -q -k "parse_hierarchy or excecoes or financeiros" 2>&1 | tail -5
```

Expected: 4 failed com `AttributeError: module 'consistency_utils' has no attribute 'parse_hierarchy'` (e `EXCECOES_SOMA`, `cnpjs_financeiros`).

- [x] **Step 3: Implementar em `scripts/analysis/consistency_utils.py`**

Atualizar `__all__`:

```python
__all__ = ["get_db", "tolerancia", "parent_code", "parse_hierarchy", "total_codes", "latest_rows",
           "cnpjs_financeiros", "new_run", "finish_run", "write_flags", "clear_flags", "add_common_args",
           "TIPOS_DOC", "FLAG_COLS", "EXCECOES_SOMA", "FORMULAS_NIVEL2", "SETOR_FINANCEIRO"]
```

Logo depois de `DVA_TOTAL_DS = ...`, acrescentar as tabelas da Camada 1:

```python
# ── Camada 1 (soma hierárquica) ──────────────────────────────────────────────
# Exceções estruturais à regra "pai = Σ filhos diretos" (plano-mãe, Fase 2):
#   'saldo': 6.05 = 6.05.02 (saldo final) − 6.05.01 (saldo inicial); bate em 99,8% dos DFPs.
#   'skip' : 3.99 (lucro por ação) e descendentes — filhos ON/PN não somam.
EXCECOES_SOMA = {
    ("DFC_MI", "6.05"): "saldo",
    ("DRE", "3.99"):    "skip",
}

# Fórmulas fixas de nível 2 (substituem a calibração empírica do plano original;
# acerto de 99,8–100% nos DFPs 2019–2024 não financeiros). Só para empresas fora
# de companies.setor = 'Financeiro' (plano COSIF diverge do nível 2 em diante).
# Termo ausente do documento conta como 0; alvo ausente → fórmula não é checada.
FORMULAS_NIVEL2 = {
    "DRE":    [("3.03", ["3.01", "3.02"]), ("3.05", ["3.03", "3.04"]), ("3.07", ["3.05", "3.06"]),
               ("3.09", ["3.07", "3.08"]), ("3.11", ["3.09", "3.10"])],
    "DFC_MI": [("6.05", ["6.01", "6.02", "6.03", "6.04"])],
}
SETOR_FINANCEIRO = "Financeiro"
```

Logo depois de `parent_code`, acrescentar:

```python
def parse_hierarchy(codes) -> dict[str, list[str]]:
    """{pai: [filhos diretos]} só para pais PRESENTES em `codes` (a DRE não tem
    conta '3', então 3.01 não tem pai; 3.01.01 tem). Preserva a ordem de entrada
    e ignora duplicatas."""
    presentes = list(dict.fromkeys(codes))
    conjunto = set(presentes)
    filhos: dict[str, list[str]] = {}
    for cd in presentes:
        pai = parent_code(cd)
        if pai is not None and pai in conjunto:
            filhos.setdefault(pai, []).append(cd)
    return filhos
```

Logo depois de `latest_rows`, acrescentar:

```python
def cnpjs_financeiros(conn: sqlite3.Connection) -> set[str]:
    """CNPJs com companies.setor = 'Financeiro' (plano COSIF): sem fórmulas de nível 2."""
    return {r[0] for r in conn.execute("SELECT cnpj FROM companies WHERE setor = ?", (SETOR_FINANCEIRO,))}
```

- [x] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_utils.py -q 2>&1 | tail -3
```

Expected: todos passam (17 testes: 13 anteriores + 4 novos).

- [x] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/consistency_utils.py tests/test_consistency_utils.py && git commit -q -m "feat(analysis): parse_hierarchy, EXCECOES_SOMA, FORMULAS_NIVEL2 e cnpjs_financeiros (Camada 1)" && git log --oneline -1
```

---

### Task 2: `check_hierarchy_sums.py` — lógica pura da Camada 1

**Files:**
- Create: `scripts/analysis/check_hierarchy_sums.py`
- Test: `tests/test_consistency_hierarchy.py`

- [x] **Step 1: Escrever os testes que falham**

Criar `tests/test_consistency_hierarchy.py`:

```python
"""
Fase 2 da consistência financeira: Camada 1 (soma hierárquica intra-documento).
Testa a lógica pura (DataFrame → flags), sem banco; main() ao final com banco em memória.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_hierarchy_sums as chs

CNPJ = "84.429.695/0001-11"
BPA_OK = {
    "1":       ("Ativo Total", 100e6),
    "1.01":    ("Ativo Circulante", 60e6),
    "1.01.01": ("Caixa", 25e6),
    "1.01.02": ("Contas a Receber", 35e6),
    "1.02":    ("Ativo Não Circulante", 40e6),
}


def _doc(contas, tipo_doc="BPA", fonte="DFP", data_ref="2023-12-31", ordem="Último",
         p_ini="NA", p_fim="2023-12-31"):
    """Linhas de UM (documento, ordem, período), no formato de latest_rows."""
    return [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref,
             "versao": 1, "ordem_exercicio": ordem, "periodo_ini": p_ini, "periodo_fim": p_fim,
             "cd_conta": cd, "ds_conta": ds, "vl_conta": vl, "st_conta_fixa": "S"}
            for cd, (ds, vl) in contas.items()]


def _df(*docs):
    return pd.DataFrame([r for d in docs for r in d])


def _por_conta(flags):
    return {f["cd_conta"]: f for f in flags}


# ── check_document ───────────────────────────────────────────────────────────

def test_arvore_que_bate_nao_gera_flag():
    flags, checados = chs.check_document(pd.DataFrame(_doc(BPA_OK)), "BPA")
    assert flags == []
    assert checados == 2                         # pais "1" e "1.01"


def test_nao_detalhado_pai_preenchido_filhos_zero_ou_nulos():
    contas = dict(BPA_OK, **{"1.01.01": ("Caixa", 0.0), "1.01.02": ("Contas a Receber", None)})
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01", "nao_detalhado", "info")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"], f["diff_rel"]) == (60e6, 0.0, -60e6, -1.0)
    assert f["cd_conta_pai"] == "1" and f["ds_conta"] == "Ativo Circulante"
    assert f["detalhe"] == {"regra": "soma", "filhos": ["1.01.01", "1.01.02"], "filhos_nao_zero": 0}


def test_pai_vazio_pai_nulo_ou_zero_com_filho_preenchido():
    contas = dict(BPA_OK, **{"1.01": ("Ativo Circulante", None)})
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    por = _por_conta(flags)
    assert por["1.01"]["classificacao"] == "pai_vazio" and por["1.01"]["severity"] == "warn"
    assert (por["1.01"]["valor_ref"], por["1.01"]["valor_cmp"], por["1.01"]["diff_rel"]) == (0.0, 60e6, None)
    assert por["1"]["classificacao"] == "divergencia"          # 1 = 100 ≠ 0 + 40
    contas["1.01"] = ("Ativo Circulante", 0.0)
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    assert _por_conta(flags)["1.01"]["classificacao"] == "pai_vazio"


def test_divergencia_pai_e_filhos_preenchidos_mas_nao_batem():
    contas = dict(BPA_OK, **{"1.01.02": ("Contas a Receber", 30e6)})
    flags, _ = chs.check_document(pd.DataFrame(_doc(contas)), "BPA")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("1.01", "divergencia", "error")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == (60e6, 55e6, -5e6)
    assert abs(f["diff_rel"] + 5e6 / 60e6) < 1e-12
    assert f["detalhe"]["filhos_nao_zero"] == 2


def test_excecao_6_05_saldo_final_menos_inicial():
    dfc = {"6.01": ("Operacional", 10e6), "6.02": ("Investimento", -4e6), "6.03": ("Financiamento", -3e6),
           "6.04": ("Variação Cambial", 0.0), "6.05": ("Aumento (Redução) de Caixa", 3e6),
           "6.05.01": ("Saldo Inicial", 20e6), "6.05.02": ("Saldo Final", 23e6)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dfc, "DFC_MI", p_ini="2023-01-01")), "DFC_MI")
    assert flags == []                            # soma simples daria 43e6; saldo dá 3e6
    assert checados == 2                          # pai 6.05 + fórmula 6.05
    dfc["6.05.02"] = ("Saldo Final", 24e6)
    flags, _ = chs.check_document(pd.DataFrame(_doc(dfc, "DFC_MI", p_ini="2023-01-01")), "DFC_MI")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["valor_cmp"]) == ("6.05", "divergencia", 4e6)
    assert f["detalhe"]["regra"] == "saldo"


def test_excecao_3_99_lucro_por_acao_ignorado():
    dre = {"3.99": ("Lucro por Ação", 1.5), "3.99.01": ("Básico", 1.5), "3.99.02": ("Diluído", 1.4),
           "3.99.01.01": ("ON", 1.5), "3.99.01.02": ("PN", 1.65)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE",
                                         formulas=False)
    assert flags == [] and checados == 0


def test_formula_nivel2_com_custo_negativo():
    dre = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 40e6),
           "3.04": ("Despesas", -10e6), "3.05": ("EBIT", 30e6)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    assert flags == []
    assert checados == 2                          # fórmulas 3.03 e 3.05 (3.07/3.09/3.11 ausentes: puladas)
    dre["3.05"] = ("EBIT", 35e6)
    flags, _ = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    f, = flags
    assert (f["cd_conta"], f["classificacao"], f["severity"]) == ("3.05", "divergencia_formula", "error")
    assert (f["valor_ref"], f["valor_cmp"], f["diff_abs"]) == (35e6, 30e6, -5e6)
    assert f["cd_conta_pai"] == "3" and f["ds_conta"] == "EBIT"
    assert f["detalhe"] == {"regra": "formula", "formula": "3.05 = 3.03 + 3.04",
                            "termos": {"3.03": 40e6, "3.04": -10e6}}


def test_formula_termo_ausente_conta_como_zero_e_formulas_false_pula():
    dre = {"3.01": ("Receita", 100e6), "3.03": ("Resultado Bruto", 100e6)}
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    assert flags == [] and checados == 1
    dre["3.03"] = ("Resultado Bruto", 90e6)
    flags, _ = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE")
    assert [f["classificacao"] for f in flags] == ["divergencia_formula"]
    flags, checados = chs.check_document(pd.DataFrame(_doc(dre, "DRE", p_ini="2023-01-01")), "DRE",
                                         formulas=False)
    assert flags == [] and checados == 0


def test_tolerancia_piso_e_relativa():
    contas = {"1": ("Ativo Total", 1e9), "1.01": ("Ativo Circulante", 1e9 + 4e6),        # 0,4%
              "2": ("Passivo Total", 50_000.0), "2.01": ("Circulante", 50_900.0)}        # +900 < piso
    doc = pd.DataFrame(_doc(contas))
    assert chs.check_document(doc, "BPA", tol_rel=0.005)[0] == []
    assert {f["cd_conta"] for f in chs.check_document(doc, "BPA", tol_rel=0.001)[0]} == {"1"}
    assert {f["cd_conta"] for f in chs.check_document(doc, "BPA", tol_abs=500.0)[0]} == {"2"}


# ── check_hierarchy_sums (agrupamento) ───────────────────────────────────────

def test_grupos_por_documento_ordem_e_periodo():
    tri = {"3.01": ("Receita", 50e6), "3.02": ("Custo", -30e6), "3.03": ("Resultado Bruto", 20e6)}
    acu = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 45e6)}   # 45 ≠ 40
    pen = {"3.01": ("Receita", 90e6), "3.02": ("Custo", -50e6), "3.03": ("Resultado Bruto", 40e6)}
    df = _df(
        _doc(tri, "DRE", "ITR", "2023-06-30", "Último",    "2023-04-01", "2023-06-30"),
        _doc(acu, "DRE", "ITR", "2023-06-30", "Último",    "2023-01-01", "2023-06-30"),
        _doc(pen, "DRE", "ITR", "2023-06-30", "Penúltimo", "2022-01-01", "2022-06-30"),
    )
    flags, stats = chs.check_hierarchy_sums(df)
    f, = flags
    assert (f["periodo_ini"], f["periodo_fim"], f["ordem_ref"]) == ("2023-01-01", "2023-06-30", "Último")
    assert (f["layer"], f["check_type"], f["cnpj_companhia"], f["tipo_doc"]) == (1, "hierarchy_sum", CNPJ, "DRE")
    assert (f["fonte_ref"], f["data_ref"]) == ("ITR", "2023-06-30")
    assert f.get("fonte_cmp") is None and f.get("data_cmp") is None
    assert stats == {"DRE": {"grupos": 3, "pais": 3, "nao_detalhado": 0, "pai_vazio": 0,
                             "divergencia": 0, "divergencia_formula": 1}}


def test_formulas_desligadas_para_o_dataframe_inteiro():
    dre = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 45e6)}
    flags, stats = chs.check_hierarchy_sums(_df(_doc(dre, "DRE", p_ini="2023-01-01")), formulas=False)
    assert flags == [] and stats["DRE"]["pais"] == 0


def test_dataframe_vazio():
    assert chs.check_hierarchy_sums(pd.DataFrame()) == ([], {})


# ── main(): ponta a ponta com banco em memória ───────────────────────────────

import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
BANCO = "60.746.948/0001-12"


def _db_com_docs():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.executemany("INSERT INTO companies (cnpj, ticker, nome_cvm, setor) VALUES (?,?,?,?)",
                     [(CNPJ, "WEGE3", "WEG", "Industrial"), (BANCO, "BBDC4", "BRADESCO", "Financeiro")])
    bpa = dict(BPA_OK, **{"1.01.01": ("Caixa", 0.0), "1.01.02": ("Contas a Receber", 0.0)})   # nao_detalhado em 1.01
    dre = {"3.01": ("Receita", 100e6), "3.02": ("Custo", -60e6), "3.03": ("Resultado Bruto", 45e6)}  # fórmula falha
    rows = (_doc(bpa) + _doc(dre, "DRE", p_ini="2023-01-01")
            + [dict(r, cnpj_companhia=BANCO) for r in _doc(dre, "DRE", p_ini="2023-01-01")])
    cols = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio",
            "dt_ini_exerc", "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
    conn.executemany(
        f"INSERT INTO demonstrativos_contabeis ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(None if (c == "dt_ini_exerc" and r["periodo_ini"] == "NA") else
               r["periodo_ini"] if c == "dt_ini_exerc" else
               r["periodo_fim"] if c == "dt_fim_exerc" else r[c] for c in cols) for r in rows],
    )
    conn.commit()
    return conn


def test_main_grava_run_e_flags_e_substitui_anteriores(monkeypatch, capsys):
    conn = _db_com_docs()
    monkeypatch.setattr(chs, "get_db", lambda: conn)

    run1 = chs.main(["--cnpj", CNPJ])
    got = conn.execute("SELECT tipo_doc, cd_conta, classificacao, severity FROM consistency_flags "
                       "WHERE run_id = ? ORDER BY tipo_doc", (run1,)).fetchall()
    assert got == [("BPA", "1.01", "nao_detalhado", "info"), ("DRE", "3.03", "divergencia_formula", "error")]
    run = conn.execute("SELECT layer, check_type, escopo, total_checked, total_flagged, finished_at "
                       "FROM consistency_runs WHERE run_id = ?", (run1,)).fetchone()
    assert run[:5] == (1, "hierarchy_sum", f"cnpj={CNPJ}", 3, 2) and run[5] is not None   # pais 1, 1.01 + fórmula 3.03

    run2 = chs.main(["--cnpj", CNPJ, "--tipo-doc", "BPA"])
    assert conn.execute("SELECT COUNT(*) FROM consistency_flags").fetchone()[0] == 2   # substituiu a BPA, manteve a DRE
    assert conn.execute("SELECT run_id FROM consistency_flags WHERE tipo_doc = 'BPA'").fetchone()[0] == run2
    assert conn.execute("SELECT run_id FROM consistency_flags WHERE tipo_doc = 'DRE'").fetchone()[0] == run1

    out = capsys.readouterr().out
    assert "BPA" in out and "nao_detalhado=1" in out and "divergencia_formula=1" in out


def test_main_full_pula_formulas_no_setor_financeiro(monkeypatch):
    conn = _db_com_docs()
    monkeypatch.setattr(chs, "get_db", lambda: conn)
    run_id = chs.main(["--full"])
    assert conn.execute("SELECT escopo FROM consistency_runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "full"
    got = conn.execute("SELECT cnpj_companhia, classificacao FROM consistency_flags ORDER BY 1, 2").fetchall()
    assert got == [(CNPJ, "divergencia_formula"), (CNPJ, "nao_detalhado")]   # o banco não gera flag de fórmula


def test_main_exige_cnpj_ou_full(monkeypatch):
    monkeypatch.setattr(chs, "get_db", lambda: _db_com_docs())
    import pytest
    with pytest.raises(SystemExit):
        chs.main([])
```

- [x] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_hierarchy.py -q 2>&1 | tail -3
```

Expected: erro de coleta `ModuleNotFoundError: No module named 'check_hierarchy_sums'`.

- [x] **Step 3: Criar `scripts/analysis/check_hierarchy_sums.py` (lógica pura + CLI)**

```python
"""
Camada 1 — soma hierárquica intra-documento (check_type = 'hierarchy_sum').

Dentro de cada (documento, ordem_exercicio, período) na versão máxima, verifica
se cada conta-pai presente é igual à soma dos filhos diretos e se as fórmulas
fixas de nível 2 (DRE e DFC_MI, só fora do setor Financeiro) fecham. É o teste
de regressão da ingestão: uma falha aqui é sintoma de documento parcial ou de
período misturado, não de reapresentação (isso é a Camada 2).

Classificação por pai (tolerância |Σ filhos − pai| ≤ max(tol_abs, tol_rel × |pai|), NULL = 0):
  - bate                                         → sem flag
  - pai ≠ 0 e todos os filhos 0/NULL             → 'nao_detalhado' (info)
  - pai 0/NULL e algum filho ≠ 0                 → 'pai_vazio' (warn)
  - pai ≠ 0, filhos ≠ 0, diferença > tolerância  → 'divergencia' (error)
  - fórmula de nível 2 não fecha                 → 'divergencia_formula' (error)
Exceções (consistency_utils.EXCECOES_SOMA): DFC_MI 6.05 = 6.05.02 − 6.05.01
('saldo'); DRE 3.99 e descendentes ignorados ('skip'). Filho sem pai no
documento (ex: 3.01 — a DRE não tem conta '3') não é checado.

Cada flag guarda o documento em fonte_ref/data_ref/ordem_ref (fonte_cmp/data_cmp
ficam NULL), valor_ref = pai, valor_cmp = soma (ou saldo, ou soma da fórmula),
diff_abs = valor_cmp − valor_ref e detalhe = {regra, filhos, filhos_nao_zero} ou
{regra: 'formula', formula, termos}. Flags anteriores do mesmo (cnpj[, tipo_doc])
são apagadas antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) logo após ingest_dfp/ingest_itr,
na base inteira. À mão (na pasta scripts/analysis, .venv ativo):
  python check_hierarchy_sums.py --cnpj 84.429.695/0001-11
  python check_hierarchy_sums.py --cnpj 84.429.695/0001-11 --tipo-doc DRE --desde 2023
  python check_hierarchy_sums.py --full          # base inteira (~145 empresas)
"""
import pandas as pd

from consistency_utils import (EXCECOES_SOMA, FORMULAS_NIVEL2, add_common_args, clear_flags,
                               cnpjs_financeiros, finish_run, get_db, latest_rows, new_run,
                               parent_code, parse_hierarchy, tolerancia, write_flags)

LAYER = 1
CHECK_TYPE = "hierarchy_sum"
SEVERITY = {"nao_detalhado": "info", "pai_vazio": "warn",
            "divergencia": "error", "divergencia_formula": "error"}
GROUP_COLS = ["cnpj_companhia", "tipo_doc", "fonte", "data_referencia", "ordem_exercicio",
              "periodo_ini", "periodo_fim"]


def _valor(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def _classificar(pai: float, soma: float, filhos_nao_zero: int, tol_abs: float, tol_rel: float):
    """Classe da falha ou None quando bate. `pai` já com NULL = 0."""
    if abs(soma - pai) <= tolerancia(pai, tol_abs, tol_rel):
        return None
    if pai != 0 and filhos_nao_zero == 0:
        return "nao_detalhado"
    if pai == 0:
        return "pai_vazio"
    return "divergencia"


def _flag(cd: str, ds, pai: float, soma: float, classe: str, detalhe: dict) -> dict:
    return {
        "cd_conta": cd,
        "cd_conta_pai": parent_code(cd),
        "ds_conta": None if ds is None or pd.isna(ds) else ds,
        "valor_ref": pai,
        "valor_cmp": soma,
        "diff_abs": soma - pai,
        "diff_rel": (soma - pai) / abs(pai) if pai else None,
        "classificacao": classe,
        "severity": SEVERITY[classe],
        "detalhe": detalhe,
    }


def _ignorado(cd: str, skips: list[str]) -> bool:
    return any(cd == s or cd.startswith(s + ".") for s in skips)


def check_document(doc: pd.DataFrame, tipo_doc: str, tol_abs: float = 1000.0,
                   tol_rel: float = 0.01, formulas: bool = True) -> tuple[list[dict], int]:
    """Linhas de UM (documento, ordem_exercicio, período). Retorna (flags, n_checados):
    flags só com os campos da linha (o chamador acrescenta o contexto); n_checados
    = pais verificados + fórmulas verificadas."""
    valores = dict(zip(doc["cd_conta"], doc["vl_conta"]))
    nomes = dict(zip(doc["cd_conta"], doc["ds_conta"]))
    skips = [cd for (t, cd), regra in EXCECOES_SOMA.items() if t == tipo_doc and regra == "skip"]
    flags: list[dict] = []
    checados = 0

    for pai, filhos in parse_hierarchy(valores).items():
        if _ignorado(pai, skips):
            continue
        regra = EXCECOES_SOMA.get((tipo_doc, pai), "soma")
        vals = {cd: _valor(valores[cd]) for cd in filhos}
        if regra == "saldo":
            soma = vals.get(f"{pai}.02", 0.0) - vals.get(f"{pai}.01", 0.0)
        else:
            soma = sum(vals.values())
        pai_v = _valor(valores[pai])
        nao_zero = sum(1 for v in vals.values() if v != 0)
        checados += 1
        classe = _classificar(pai_v, soma, nao_zero, tol_abs, tol_rel)
        if classe:
            flags.append(_flag(pai, nomes[pai], pai_v, soma, classe,
                               {"regra": regra, "filhos": filhos, "filhos_nao_zero": nao_zero}))

    if formulas:
        for alvo, termos in FORMULAS_NIVEL2.get(tipo_doc, []):
            if alvo not in valores:
                continue
            checados += 1
            pai_v = _valor(valores[alvo])
            valores_termos = {t: _valor(valores.get(t)) for t in termos}
            soma = sum(valores_termos.values())
            if abs(soma - pai_v) > tolerancia(pai_v, tol_abs, tol_rel):
                flags.append(_flag(alvo, nomes[alvo], pai_v, soma, "divergencia_formula",
                                   {"regra": "formula", "formula": f"{alvo} = {' + '.join(termos)}",
                                    "termos": valores_termos}))
    return flags, checados


def check_hierarchy_sums(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01,
                         formulas: bool = True) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"grupos": n, "pais": n_checados, <classe>: n_flags, ...},
    contando grupos (documento, ordem_exercicio, período).
    Linhas com periodo_fim NULL são ignoradas (groupby descarta NaN na chave).
    """
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return flags, stats
    for (cnpj, tipo_doc, fonte, data_ref, ordem, p_ini, p_fim), grupo in df.groupby(GROUP_COLS, sort=True):
        linhas, checados = check_document(grupo, tipo_doc, tol_abs, tol_rel, formulas)
        st = stats.setdefault(tipo_doc, {"grupos": 0, "pais": 0, **{c: 0 for c in SEVERITY}})
        st["grupos"] += 1
        st["pais"] += checados
        for linha in linhas:
            st[linha["classificacao"]] += 1
        contexto = {
            "layer": LAYER, "check_type": CHECK_TYPE,
            "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
            "periodo_ini": p_ini, "periodo_fim": p_fim,
            "fonte_ref": fonte, "data_ref": data_ref, "ordem_ref": ordem,
        }
        flags.extend({**contexto, **linha} for linha in linhas)
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
    """Roda a Camada 1 e devolve o run_id. `argv=None` lê sys.argv."""
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
    financeiros = cnpjs_financeiros(conn)
    run_id = new_run(conn, LAYER, CHECK_TYPE, _escopo(args), vars(args))
    print(f"run {run_id}: {len(cnpjs)} empresa(s), tol_abs={args.tol_abs} tol_rel={args.tol_rel}, "
          f"{len(financeiros)} sem fórmulas de nível 2 (setor Financeiro)")

    total_checked = total_flagged = 0
    stats_total: dict = {}
    for i, cnpj in enumerate(cnpjs, 1):
        df = latest_rows(conn, cnpj=cnpj, tipo_doc=args.tipo_doc, desde=args.desde, ate=args.ate)
        flags, stats = check_hierarchy_sums(df, args.tol_abs, args.tol_rel, formulas=cnpj not in financeiros)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_flags(conn, run_id, flags)
        pais = sum(s["pais"] for s in stats.values())
        total_checked += pais
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {pais} pais/fórmulas, {n} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (grupos = documento × ordem × período):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        classes = " ".join(f"{c}={s[c]}" for c in SEVERITY)
        print(f"  {tipo:7s} grupos={s['grupos']} pais={s['pais']} {classes}")
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_hierarchy.py -q 2>&1 | tail -3
```

Expected: 15 passed.

- [x] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/check_hierarchy_sums.py tests/test_consistency_hierarchy.py && git commit -q -m "feat(analysis): Camada 1 — check_hierarchy_sums (soma hierárquica, exceções 6.05/3.99, fórmulas de nível 2)" && git log --oneline -1
```

---

### Task 3: `run_all.py` + `update_weekly.sh`

**Files:**
- Modify: `scripts/analysis/run_all.py`
- Modify: `scripts/update_weekly.sh`

- [x] **Step 1: Registrar a camada 1 em `run_all.py`**

Substituir o import e o registro:

```python
import check_cross_period
import check_hierarchy_sums

LAYERS = {
    1: check_hierarchy_sums.main,
    2: check_cross_period.main,
}
```

E atualizar a docstring: trocar `Camadas disponíveis crescem a cada fase do plano (1 = soma hierárquica, 3 = granularidade, 5 = trilha temporal, 6 = desacúmulo). update_weekly.sh chama `run_all.py --layer 2 --full`` por `Camadas disponíveis crescem a cada fase do plano (3 = granularidade, 5 = trilha temporal, 6 = desacúmulo). update_weekly.sh chama `run_all.py --layer 1 --full` e `--layer 2 --full``, e acrescentar o exemplo `python run_all.py --layer 1,2 --cnpj 84.429.695/0001-11`.

- [x] **Step 2: Passo `consistency_l1` no `update_weekly.sh`**

Trocar o bloco de consistência por:

```bash
# Consistência dos demonstrativos — depende de DFP/ITR recém-ingeridos;
# idempotente. Camada 1 (soma hierárquica: regressão da ingestão) e Camada 2
# (reapresentações entre filings), ~1,5 min cada na base inteira. Pulado se
# os dois ingestores falharam (não haveria dado novo para checar).
if [[ " ${FAILED[*]} " == *" dfp "* && " ${FAILED[*]} " == *" itr "* ]]; then
  log "==> consistency: pulado (dfp e itr falharam)"
else
  run_step "consistency_l1" ../analysis/run_all.py --layer 1 --full
  run_step "consistency_l2" ../analysis/run_all.py --layer 2 --full
fi
```

E no cabeçalho do arquivo trocar `consistência dos demonstrativos (Camada 2)` por `consistência dos demonstrativos (Camadas 1 e 2)`.

- [x] **Step 3: Conferir que o orquestrador aceita as duas camadas e que o shell é válido**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && ../../.venv/bin/python run_all.py --help | head -12 && bash -n ../update_weekly.sh && echo shell-ok && cd ../.. && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: `--help` lista `disponíveis: 1,2`; `shell-ok`; suíte inteira verde.

- [x] **Step 4: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/run_all.py scripts/update_weekly.sh && git commit -q -m "feat(analysis): run_all --layer 1; Camada 1 no update_weekly.sh antes da Camada 2" && git log --oneline -1
```

---

### Task 4: Fumaça no banco real — WEGE3

**Files:** nenhum (só execução).

- [x] **Step 1: Rodar a Camada 1 só para a WEG**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && ../../.venv/bin/python run_all.py --layer 1 --cnpj 84.429.695/0001-11
```

Expected: termina em poucos segundos; resumo por tipo_doc com `divergencia=0` em BPA/BPP; `nao_detalhado` pequeno (≤ dezenas).

- [x] **Step 2: Verificar a forma das flags e a idempotência**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("cvm_research.db")
print(c.execute("SELECT tipo_doc, classificacao, severity, COUNT(*) FROM consistency_flags WHERE layer=1 AND cnpj_companhia='84.429.695/0001-11' GROUP BY 1,2,3 ORDER BY 1,2").fetchall())
print(c.execute("SELECT tipo_doc, cd_conta, ds_conta, periodo_ini, periodo_fim, fonte_ref, data_ref, ordem_ref, valor_ref, valor_cmp, detalhe FROM consistency_flags WHERE layer=1 AND cnpj_companhia='84.429.695/0001-11' ORDER BY severity DESC, data_ref DESC LIMIT 5").fetchall())
print("fonte_cmp sempre NULL:", c.execute("SELECT COUNT(*) FROM consistency_flags WHERE layer=1 AND fonte_cmp IS NOT NULL").fetchone())
EOF
cd scripts/analysis && ../../.venv/bin/python run_all.py --layer 1 --cnpj 84.429.695/0001-11 | tail -1 && cd ../.. && .venv/bin/python -c "
import sqlite3; c=sqlite3.connect('cvm_research.db')
print('runs L1:', c.execute(\"SELECT COUNT(*) FROM consistency_runs WHERE layer=1\").fetchone(), 'run_ids distintos nas flags L1 da WEG:', c.execute(\"SELECT COUNT(DISTINCT run_id) FROM consistency_flags WHERE layer=1 AND cnpj_companhia='84.429.695/0001-11'\").fetchone())"
```

Expected: `fonte_cmp sempre NULL: (0,)`; após a segunda execução, 2 runs em `consistency_runs` mas 1 único `run_id` nas flags (substituiu, não somou). As flags da Camada 2 (`layer=2`) da WEG continuam intactas.

---

### Task 5: Execução completa e verificação dos números esperados

**Files:**
- Modify: `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md` (seção "Verificação da Fase 2")

- [x] **Step 1: Rodar a base inteira**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && time ../../.venv/bin/python run_all.py --layer 1 --full 2>&1 | tail -12
```

Expected: ~145 empresas; resumo por tipo_doc; `divergencia` em BPA/BPP próximo de 0 na base inteira.

- [x] **Step 2: Distribuição geral e os números do plano-mãe (DFP 2023 e 2024, `Último`)**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("cvm_research.db")
print("geral:", c.execute("SELECT tipo_doc, classificacao, COUNT(*) FROM consistency_flags WHERE layer=1 GROUP BY 1,2 ORDER BY 1,2").fetchall())
print("DFP 2023+2024 Último:", c.execute("""
SELECT tipo_doc, classificacao, COUNT(*) FROM consistency_flags
WHERE layer=1 AND fonte_ref='DFP' AND data_ref IN ('2023-12-31','2024-12-31') AND ordem_ref='Último'
GROUP BY 1,2 ORDER BY 1,2""").fetchall())
print("divergencia em BPA/BPP (qualquer filing):", c.execute("""
SELECT cnpj_companhia, tipo_doc, fonte_ref, data_ref, ordem_ref, cd_conta, valor_ref, valor_cmp FROM consistency_flags
WHERE layer=1 AND classificacao='divergencia' AND tipo_doc IN ('BPA','BPP') ORDER BY data_ref DESC LIMIT 10""").fetchall())
print("run:", c.execute("SELECT run_id, total_checked, total_flagged, started_at, finished_at FROM consistency_runs WHERE layer=1 ORDER BY started_at DESC LIMIT 1").fetchone())
EOF
```

Expected (plano-mãe): `nao_detalhado` ≈ 424 em BPA e ≈ 423 em BPP; `divergencia`: BPA 0, BPP 0, DRE ≈ 8, DVA ≈ 3. **Qualquer contagem de `divergencia` em BPA/BPP acima de ~10 indica bug no `parse_hierarchy` ou na resolução de versão** — parar e investigar antes de seguir.

- [x] **Step 3: Registrar os números medidos no plano-mãe**

Acrescentar à tabela/seção "Verificação da Fase 2" do plano-mãe uma linha `**Medido em 2026-09-18, base pós-Fase 1, run `<run_id>`**` com: tempo, `total_checked`, `total_flagged`, contagens por classe em DFP 2023+2024 `Último` e o geral, e as `divergencia` em BPA/BPP encontradas (se houver, com CNPJ e conta). Acrescentar também, no topo da seção Fase 2, o ponteiro `> **Plano de tarefas (executado):** `docs/superpowers/plans/2026-09-18-fase2-camada1-hierarchy-sums.md`.`

- [x] **Step 4: Commit do registro**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md && git commit -q -m "docs(plano): numeros medidos da Camada 1 na base; ponteiro para o plano da Fase 2" && git log --oneline -1
```

---

### Task 6: Documentação

**Files:**
- Modify: `CLAUDE.md` (subseção `consistency_flags` e "Comportamento esperado ao pesquisar")
- Modify: `README.md` (árvore e tabela de camadas)
- Modify: `scripts/mcp/cvm_mcp.py` (docstring de `query`)

- [x] **Step 1: `CLAUDE.md` — subseção da tabela**

Na subseção `### consistency_flags`, trocar a frase `Gerada por `scripts/analysis/`. Roda no job semanal (`update_weekly.sh`) logo após `ingest_dfp`/`ingest_itr`, na base inteira; também pode ser rodada à mão por empresa.` por `Gerada por `scripts/analysis/`. As Camadas 1 e 2 rodam no job semanal (`update_weekly.sh`) logo após `ingest_dfp`/`ingest_itr`, na base inteira; também podem ser rodadas à mão por empresa.`

Logo antes do parágrafo `**Camada 2 (`layer = 2`, ...)**`, inserir:

```markdown
**Camada 1 (`layer = 1`, `check_type = 'hierarchy_sum'`)** — dentro de cada (documento, `ordem_exercicio`,
período), cada conta-pai presente é comparada à soma dos filhos diretos (tolerância `max(R$ 1.000, 1% × |pai|)`).
É o teste de regressão da ingestão: a flag guarda o documento em `fonte_ref/data_ref/ordem_ref` (`*_cmp` NULL),
`valor_ref` = pai, `valor_cmp` = soma dos filhos, `diff_abs = valor_cmp − valor_ref`.
- `nao_detalhado` (`info`): pai preenchido, todos os filhos 0/NULL — a empresa não abriu a conta; o pai é confiável.
- `pai_vazio` (`warn`): pai 0/NULL com filho preenchido — sintoma de ingestão parcial.
- `divergencia` (`error`): pai e filhos preenchidos e a soma não fecha.
- `divergencia_formula` (`error`): fórmula fixa de nível 2 não fecha (DRE `3.03 = 3.01 + 3.02` … `3.11 = 3.09 + 3.10`;
  DFC `6.05 = 6.01 + … + 6.04`); não é checada no setor `Financeiro` (COSIF). `detalhe = {"regra": "formula", "formula", "termos"}`.
- Exceções: DFC `6.05 = 6.05.02 − 6.05.01` (`detalhe.regra = 'saldo'`); DRE `3.99` (lucro por ação) ignorada.

Para rodar: `cd scripts/analysis && python run_all.py --layer 1 --cnpj <CNPJ>` (`--layer 1,2` roda as duas).
```

- [x] **Step 2: `CLAUDE.md` — query padrão**

Logo depois da query "Reapresentações e reclassificações de uma empresa (Camada 2)" (e do parágrafo que a segue), inserir:

```markdown
### Somas que não fecham dentro de um documento (Camada 1)
```sql
-- Só os erros (soma ou fórmula não fecha); nao_detalhado é informativo e pai_vazio é aviso
SELECT tipo_doc, fonte_ref || ' ' || data_ref || ' (' || ordem_ref || ')' AS documento,
       periodo_ini, periodo_fim, cd_conta, ds_conta, classificacao,
       valor_ref AS pai, valor_cmp AS soma_filhos, diff_abs,
       json_extract(detalhe, '$.regra') AS regra
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 1 AND severity = 'error'
ORDER BY data_ref DESC, tipo_doc, cd_conta;
```
Ausência de flags para um documento significa que todas as somas fecharam. `nao_detalhado` em BPA/BPP é comum
(a empresa publica só o total da conta) e não indica problema no valor do pai.
```

- [x] **Step 3: `CLAUDE.md` — item no "Comportamento esperado ao pesquisar"**

Depois do item 7, inserir (renumerando o antigo 8 para 9):

```markdown
8. **Antes de somar sublinhas de um demonstrativo** (ex: abrir o ativo circulante por conta): confira em
   `consistency_flags` (Camada 1) se o pai tem `nao_detalhado` — nesse caso use o valor do pai, não a soma
   dos filhos, que é zero. Um `divergencia`/`divergencia_formula` no documento é sinal de que o quadro
   está inconsistente na própria fonte; informe ao usuário e mostre pai e soma lado a lado.
```

- [x] **Step 4: `README.md` — árvore e tabela**

Na árvore, logo depois da linha `check_cross_period.py`, acrescentar:

```
│       ├── check_hierarchy_sums.py # Camada 1: soma hierárquica intra-documento (regressão da ingestão)
```

Na seção "Análise de consistência dos demonstrativos": trocar `A Camada 2 roda no job semanal` por `As Camadas 1 e 2 rodam no job semanal`; acrescentar aos exemplos `python run_all.py --layer 1,2 --cnpj 84.429.695/0001-11   # as duas camadas`; e inserir a linha na tabela, antes da linha da Camada 2:

```markdown
| 1 | `check_hierarchy_sums.py` | Dentro de cada documento, pai = Σ filhos diretos e fórmulas de nível 2 (DRE/DFC): `nao_detalhado` (pai sem abertura), `pai_vazio`, `divergencia`, `divergencia_formula`. Exceções: `6.05` = saldo final − inicial, `3.99` ignorada. |
```

- [x] **Step 5: `scripts/mcp/cvm_mcp.py` — docstring de `query`**

Na linha que descreve `consistency_flags`, acrescentar a Camada 1: `consistency_flags: achados de consistência (layer=1 hierarchy_sum: nao_detalhado/pai_vazio/divergencia/divergencia_formula dentro de um documento; layer=2 cross_period: ...)`.

- [x] **Step 6: Conferir que o MCP ainda sobe e a suíte está verde**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -c "import ast,sys; ast.parse(open('scripts/mcp/cvm_mcp.py').read()); print('mcp ok')" && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: `mcp ok`; suíte verde.

- [x] **Step 7: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add CLAUDE.md README.md scripts/mcp/cvm_mcp.py && git commit -q -m "docs: Camada 1 (hierarchy_sum) no CLAUDE.md, README e docstring do MCP" && git log --oneline -1
```

---

## Verificação geral da Fase 2

- `pytest tests/` verde, sem tocar `cvm_research.db`.
- `run_all.py --layer 1 --full` executado; números registrados no plano-mãe e coerentes com a seção "Verificação da Fase 2" (`divergencia` em BPA/BPP ≈ 0).
- `update_weekly.sh` passa `bash -n`; passos `consistency_l1` e `consistency_l2` independentes.
- Flags da Camada 2 intactas após rodar a Camada 1 (`clear_flags` filtra por `layer`/`check_type`).
- Branch `fase-2-camada-1` pronto para merge em `main`.
