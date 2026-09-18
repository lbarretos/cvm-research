# Casamento de linhas no desacúmulo (correção da Camada 6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a Camada 6 subtrair acumulados casando **a mesma linha** nos dois filings, e não o mesmo `cd_conta`, eliminando os ~24,6 mil valores trimestrais silenciosamente errados que a renumeração de contas produz hoje.

**Architecture:** A escada de casamento da Camada 5 (`_comparar_pai`/`compare_filings` em `check_text_stability.py`) já resolve o problema: casa linhas pai a pai por código fixo da CVM, depois por nome normalizado (`renumerado`), depois por similaridade (`reformulacao` ≥ 0,75; `ambiguo` entre 0,55 e 0,75). Ela só não é usada pela Camada 6. Esta fase expõe essa escada como `match_filings(anterior, atual)`, que devolve `{cd no atual: (cd no anterior, classe, score)}` para **qualquer** par de filings — inclusive DFP × ITR do 3T, que a Camada 5 nunca compara porque agrupa por fonte. A Camada 6 passa a consultar esse mapa em vez de indexar `b["acum"][cd]`. Por decisão do usuário, pares `ambiguo` **não** são casados automaticamente: viram `vl_derivado` NULL, flag `par_ambiguo` (fila de revisão) e ficam registrados com o candidato no `detalhe`. Duas colunas novas em `demonstrativos_trimestrais` (`cd_conta_b`, `casamento`) tornam a subtração auditável.

**Tech Stack:** Python 3 + pandas + SQLite (`scripts/analysis/`), pytest, `difflib` (já embutido em `consistency_utils.text_similarity`).

---

## Contexto: o bug, medido

Reproduzido em 18/09/2026 na Multiplan (`07.816.890/0001-53`), DFC_MI, conta `6.03.08`.

A empresa reordena os códigos da DFC entre o 1T e o 2T todo ano, e usa um layout diferente no DFP. Hoje `derive_quarters.py` faz `b["acum"][cd]`, casando por código puro:

| Onde | Valor gravado hoje | Subtraendo que usou | Valor correto | Flag hoje |
|---|---|---|---|---|
| 2T26 `6.03.08` Pagamento de encargos sobre debêntures | -249,5 mi | `6.03.08` do 1T = **Dividendos e JCP** | **-202,1 mi** | nenhuma |
| 2T26 `6.03.09` Dividendos e JCP | NULL | — | **-105,9 mi** | `linha_sem_par` |
| 4T25 `6.03.08` Aumento de capital social | **+352,5 mi** | `6.03.08` do ITR 3T = encargos de debêntures | NULL (não existe no 3T) | nenhuma |
| 4T25 `6.03.07` Pagamento de encargos sobre debêntures | -560,1 mi | `6.03.07` do ITR 3T = Gastos com operações de ações | **-207,6 mi** | nenhuma |
| 4T25 `6.03.09` Gastos com operações de ações | **-482,9 mi** | `6.03.09` do ITR 3T = Captação de debêntures | 0,0 | nenhuma |

Escala na base inteira (linhas derivadas cujo subtraendo tem nome diferente, safra original):

| tipo_doc | 2T | 3T | 4T |
|---|---|---|---|
| DFC_MI | 21,6% | 20,9% | 39,1% |
| DRE | 2,2% | 2,1% | 3,9% |
| DVA | 1,2% | 0,9% | 2,0% |

Cruzando com a Camada 5 para separar o retoque benigno de texto (mesmo código, mesma linha) do descasamento real, na DFC de 2T mais 3T, safra original:

| Situação | Linhas | Sem nenhuma flag |
|---|---|---|
| Renumerado de outro código | 16.765 | 13.018 |
| Linha nova ocupando código reciclado | 13.051 | 6.486 |
| Reformulação vinda de outro código | 4.956 | 3.866 |
| Ambíguo vindo de outro código | 1.614 | 1.207 |
| Texto retocado no mesmo código (benigno, já correto) | 10.173 | — |

As 145 empresas da base têm pelo menos um caso.

## Protótipo já validado (18/09/2026)

`compare_filings` aplicado aos dois pares que falham na Multiplan produz exatamente os números certos. Registrado aqui porque é a premissa do plano inteiro:

```
### ITR 2026-06-30  −  ITR 2026-03-31   (estáveis=43)
6.03.08  Pagamento de encargos sobre debêntures  ← 6.03.06  reformulacao 0.9444   -202.1
6.03.09  Dividendos e juros sobre o capital ...  ← 6.03.08  reformulacao 0.9512   -105.9
6.03.10  Gastos com operações de ações           ← 6.03.07  renumerado   1.0          0.0
6.03.06  Pagamento de debêntures                 ← sem par                          NULL

### DFP 2025-12-31  −  ITR 2025-09-30   (estáveis=17)
6.03.07  Pagamento de encargos sobre debêntures  ← 6.03.08  renumerado   1.0       -207.6
6.03.11  Dividendos pagos e juros sobre cap ...  ← 6.03.06  reformulacao 0.9787    -175.6
6.03.13  Participação de não controladores       ← 6.03.04  renumerado   1.0         -0.1
6.03.12  Emissão de debêntures                   ← 6.03.09  ambiguo      0.7442  BLOQUEADO
6.03.08  Aumento de capital social               ← sem par                          NULL
```

O par `ambiguo` (`Emissão de debêntures` × `Captação de debêntures`, score 0,7442) é um casamento verdadeiro que ficará bloqueado por decisão do usuário. Isso é o esperado: vira fila de revisão, não valor silencioso.

## Decisões de desenho

1. **Não casar `ambiguo` automaticamente** (decisão do usuário, 18/09/2026). `vl_derivado` NULL, `flag = 'par_ambiguo'`, flag de linha em `consistency_flags` com o candidato e o score no `detalhe`.
2. **Reusar a Camada 5 em vez de duplicar a escada.** `derive_quarters` importa de `check_text_stability`, seguindo o precedente de `check_granularity` importar `iter_pairs` de `check_cross_period`.
3. **Casar dentro da Camada 6, não ler `cd_conta_ds_timeline`.** A trilha cobre só `ordem_exercicio = 'Último'` e só pares da mesma fonte, então não serve para a safra `reapresentado` (colunas `Penúltimo`) nem para o 4T (DFP × ITR). Um caminho único é mais simples que dois.
4. **`linha_sem_par` muda de sentido**, de "código ausente no acumulado anterior" para "linha sem correspondente no acumulado anterior". O nome continua correto e a contagem vai subir.
5. **Migração por DROP + recriação.** `demonstrativos_trimestrais` é 100% derivada e já é regravada inteira a cada run.

## File Structure

- **Modify:** `scripts/analysis/check_text_stability.py` — `compare_filings` devolve o mapa; nova `match_filings`.
- **Modify:** `scripts/analysis/derive_quarters.py` — `docs_acumulados` guarda `st_conta_fixa`; `_derivar_exercicio` usa `match_filings`; nova flag, novas colunas, novos argumentos de CLI.
- **Modify:** `schema.sql` — `demonstrativos_trimestrais` ganha `cd_conta_b` e `casamento`; CHECK de `flag` ganha `par_ambiguo`.
- **Create:** `scripts/migrations/2026-09-18_trimestrais_casamento.sql` — derruba a tabela derivada para o `schema.sql` recriá-la.
- **Modify:** `tests/test_consistency_text.py` — testes de `match_filings`.
- **Modify:** `tests/test_derive_quarters.py` — testes do casamento no desacúmulo.
- **Create:** `tests/test_derive_quarters_real.py` — validação contra o banco de produção em 2017, 2021 e 2025.
- **Modify:** `CLAUDE.md`, `README.md` — documentar as colunas novas, a flag nova e o que mudou na leitura da tabela.

---

### Task 1: `match_filings` — expor a escada de casamento da Camada 5

**Files:**
- Modify: `scripts/analysis/check_text_stability.py:132-166` (`compare_filings`) e `:190` (o único chamador)
- Test: `tests/test_consistency_text.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao final de `tests/test_consistency_text.py`:

```python
# ── match_filings: casamento reaproveitado pela Camada 6 ─────────────────────

def test_match_filings_devolve_par_classe_e_score():
    anterior = {"6.03": ("Financiamento", "S"),
                "6.03.01": ("Pagamento de empréstimos", "N"),
                "6.03.06": ("Pagamento de encargos e debêntures", "N"),
                "6.03.08": ("Dividendos e juros sobre capital próprio", "N")}
    atual = {"6.03": ("Financiamento", "S"),
             "6.03.01": ("Pagamento de empréstimos", "N"),
             "6.03.08": ("Pagamento de encargos sobre debêntures", "N"),
             "6.03.09": ("Dividendos e juros sobre capital próprio", "N"),
             "6.03.11": ("Exercício de ações restritas", "N")}
    par = ts.match_filings(anterior, atual)
    assert par["6.03"] == ("6.03", "estavel", None)
    assert par["6.03.01"] == ("6.03.01", "estavel", None)
    assert par["6.03.09"] == ("6.03.08", "renumerado", 1.0)          # nome idêntico, código novo
    cd_b, classe, score = par["6.03.08"]
    assert (cd_b, classe) == ("6.03.06", "reformulacao") and score >= 0.75
    assert "6.03.11" not in par                                      # linha nova: sem par


def test_match_filings_marca_ambiguo_sem_casar_silenciosamente():
    anterior = {"6.03": ("Financiamento", "S"), "6.03.09": ("Captação de debêntures", "N")}
    atual = {"6.03": ("Financiamento", "S"), "6.03.12": ("Emissão de debêntures", "N")}
    cd_b, classe, score = ts.match_filings(anterior, atual)["6.03.12"]
    assert (cd_b, classe) == ("6.03.09", "ambiguo") and 0.55 < score < 0.75


def test_match_filings_vazio_dos_dois_lados():
    assert ts.match_filings({}, {}) == {}
    assert ts.match_filings({}, {"3.01": ("Receita", "S")}) == {}


def test_compare_filings_devolve_o_mapa_anterior_para_atual():
    anterior = {"6.01": ("Operacional", "S"), "6.01.01": ("Depreciação", "N")}
    atual = {"6.01": ("Operacional", "S"), "6.01.07": ("Depreciação", "N")}
    rows, estaveis, mapa = ts.compare_filings(anterior, atual)
    assert mapa == {"6.01": "6.01", "6.01.01": "6.01.07"} and estaveis == 1
    assert [r["classificacao"] for r in rows] == ["renumerado"]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_consistency_text.py -q -k "match_filings or devolve_o_mapa" 2>&1 | tail -5
```

Expected: 4 failed. Três com `AttributeError: module 'check_text_stability' has no attribute 'match_filings'` e uma com `ValueError: not enough values to unpack (expected 3, got 2)`.

- [ ] **Step 3: Implementar**

Em `scripts/analysis/check_text_stability.py`, na docstring do módulo, trocar o parágrafo que começa em "Grava em cd_conta_ds_timeline" por:

```
Grava em cd_conta_ds_timeline (data_referencia = filing B; 'removida' com
cd_conta/ds_conta da linha antiga; cd_conta_anterior/ds_conta_anterior/
similarity_score quando há par) e em consistency_flags só os 'ambiguo'.
Linhas anteriores do mesmo (cnpj[, tipo_doc]) são apagadas nas duas tabelas
antes de gravar.

`match_filings` expõe a mesma escada para a Camada 6 (derive_quarters), que
precisa casar pares de filings que esta camada não compara: colunas
'Penúltimo' e DFP × ITR do 3T.
```

Trocar a assinatura e o `return` de `compare_filings` (o corpo fica igual):

```python
def compare_filings(A: dict, B: dict, sim_alto: float = SIM_ALTO,
                    sim_baixo: float = SIM_BAIXO) -> tuple[list[dict], int, dict]:
    """A/B = {cd: (ds, st)} de dois filings consecutivos. Retorna (rows sem contexto,
    n_estaveis, mapa código em A → código em B de todas as linhas casadas, inclusive
    as estáveis). Processa os pais da raiz para as folhas; o mapa A→B dos pais já
    casados escolhe os filhos de A que correspondem a cada pai de B."""
```

```python
    return rows, estaveis, mapa
```

Ajustar o único chamador, em `check_text_stability`:

```python
                novas, estaveis, _ = compare_filings(linhas_ant, atual, sim_alto, sim_baixo)
```

Acrescentar logo depois de `compare_filings`, antes de `check_text_stability`:

```python
CASADAS = ("renumerado", "reformulacao", "ambiguo")


def match_filings(anterior: dict, atual: dict, sim_alto: float = SIM_ALTO,
                  sim_baixo: float = SIM_BAIXO) -> dict:
    """Casa as linhas de dois filings quaisquer com a escada desta camada. Ao contrário
    de check_text_stability, não exige que sejam consecutivos nem da mesma fonte: a
    Camada 6 usa isto para DFP × ITR do 3T e para as colunas 'Penúltimo'.

    anterior/atual = {cd_conta: (ds_conta, st_conta_fixa)}.
    Retorna {cd no `atual`: (cd no `anterior`, classificacao, similarity_score)} só para
    as linhas casadas; classificacao ∈ CASADAS + 'estavel' (score None). Linha de `atual`
    sem correspondente em `anterior` fica de fora do dicionário."""
    rows, _estaveis, mapa = compare_filings(anterior, atual, sim_alto, sim_baixo)
    classes = {r["cd_conta"]: (r["cd_conta_anterior"], r["classificacao"], r["similarity_score"])
               for r in rows if r["classificacao"] in CASADAS}
    return {cd_at: classes.get(cd_at) or (cd_ant, "estavel", None) for cd_ant, cd_at in mapa.items()}
```

Acrescentar `"CASADAS"` e `"match_filings"` não é necessário (o módulo não tem `__all__`).

- [ ] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 166 passed (162 anteriores + 4 novos).

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/check_text_stability.py tests/test_consistency_text.py && git commit -q -m "feat(analysis): match_filings expõe a escada de casamento da Camada 5 para outros pares de filings" && git log --oneline -1
```

---

### Task 2: schema — `cd_conta_b`, `casamento` e a flag `par_ambiguo`

**Files:**
- Modify: `schema.sql` (tabela `demonstrativos_trimestrais`)
- Create: `scripts/migrations/2026-09-18_trimestrais_casamento.sql`
- Test: `tests/test_derive_quarters.py` (`test_schema_trimestrais`)

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_derive_quarters.py`, dentro de `test_schema_trimestrais`, trocar o `assert` do conjunto de colunas por:

```python
    assert {"run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
            "cd_conta", "ds_conta", "cd_conta_b", "casamento", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
            "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"} <= set(cols)
```

e acrescentar, no final da mesma função:

```python
    conn.execute(sql.replace("'3.01'", "'3.02'"), (CNPJ, "2024-10-01", "2024-12-31", 4, "par_ambiguo"))
    sql_cas = ("INSERT INTO demonstrativos_trimestrais (run_id, cnpj_companhia, tipo_doc, safra, exercicio_ini, dt_ini_exerc, "
               "dt_fim_exerc, trimestre, cd_conta, origem, casamento) VALUES ('r', ?, 'DRE', 'original', '2024-01-01', ?, ?, ?, ?, 'derivado', ?)")
    conn.execute(sql_cas, (CNPJ, "2024-10-01", "2024-12-31", 4, "3.03", "reformulacao"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql_cas, (CNPJ, "2024-10-01", "2024-12-31", 4, "3.04", "inventado"))   # CHECK casamento
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_derive_quarters.py::test_schema_trimestrais -q 2>&1 | tail -5
```

Expected: 1 failed, com `AssertionError` no conjunto de colunas.

- [ ] **Step 3: Implementar**

Em `schema.sql`, na tabela `demonstrativos_trimestrais`, trocar o bloco de `cd_conta` até `flag` por:

```sql
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    -- Casamento da linha entre os dois filings (Camada 5, match_filings). Sem eles a
    -- subtração não é auditável: o mesmo cd_conta pode ser outra linha no filing B.
    cd_conta_b      TEXT,                 -- código desta mesma linha no filing B (subtraendo)
    casamento       TEXT CHECK (casamento IN ('estavel','renumerado','reformulacao','ambiguo')),
    vl_publicado    REAL,                 -- linha trimestral do ITR (só DRE 1T–3T)
    vl_derivado     REAL,                 -- acum(Qn) − acum(Qn−1); DFP − acum(3T) no 4T; NULL se não deriva
    origem          TEXT NOT NULL CHECK (origem IN ('publicado','derivado')),
    vl_final        REAL,
    flag            TEXT CHECK (flag IN ('reapresentacao_intra_ano','componente_reapresentado',
                                         'linha_sem_par','par_ambiguo','sem_anterior','sem_3t','sem_dfp')),
```

Criar `scripts/migrations/2026-09-18_trimestrais_casamento.sql`:

```sql
.bail on
-- Acrescenta cd_conta_b/casamento e a flag 'par_ambiguo' a demonstrativos_trimestrais
-- (ver schema.sql). SQLite não altera um CHECK inline, e a tabela é 100% derivada:
-- derrubar e regerar é mais barato e mais seguro que copiar 1,8M linhas.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-09-18_trimestrais_casamento.sql
--   sqlite3 cvm_research.db < schema.sql
--   cd scripts/analysis && python run_all.py --layer 6 --full
--
-- IMPORTANTE — entre este script e a Camada 6 rodar de novo, a tabela fica VAZIA.
-- Nenhuma query trimestral responde nessa janela; isso é esperado.
-- Os dados descartados eram inválidos: casavam linhas pelo cd_conta, que não é
-- estável entre filings (ver docs/superpowers/plans/2026-09-18-fase6-*.md).
--
-- .bail on é essencial: sem ele uma falha no meio do script não interrompe a execução.

PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS demonstrativos_trimestrais;
PRAGMA foreign_keys = ON;
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 166 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add schema.sql scripts/migrations/2026-09-18_trimestrais_casamento.sql tests/test_derive_quarters.py && git commit -q -m "feat(schema): cd_conta_b/casamento e flag par_ambiguo em demonstrativos_trimestrais" && git log --oneline -1
```

---

### Task 3: Camada 6 subtrai a linha casada, não o mesmo código

**Files:**
- Modify: `scripts/analysis/derive_quarters.py`
- Test: `tests/test_derive_quarters.py`

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_derive_quarters.py`, o helper `_doc` fixa `st_conta_fixa: "S"`. Trocar a definição dele por uma que aceite contas criadas pela empresa (`'N'`), mantendo o default `'S'` para não mexer nos testes existentes:

```python
def _doc(fonte, data_ref, ordem, ini, fim, contas, tipo_doc="DRE", tri=None, st="S"):
    """Linhas de um documento: acumulado (ini..fim) e, se tri, a linha trimestral isolada (tri_ini..fim).
    st = st_conta_fixa das linhas ('N' = conta criada pela empresa, sujeita a renumeração)."""
    rows = [{"cnpj_companhia": CNPJ, "fonte": fonte, "tipo_doc": tipo_doc, "data_referencia": data_ref, "versao": 1,
             "ordem_exercicio": ordem, "periodo_ini": ini, "periodo_fim": fim, "cd_conta": cd, "ds_conta": ds,
             "vl_conta": vl, "st_conta_fixa": st} for cd, (ds, vl) in contas.items()]
    if tri:
        tri_ini, tri_contas = tri
        rows += [dict(r, periodo_ini=tri_ini, vl_conta=tri_contas[r["cd_conta"]]) for r in rows if r["cd_conta"] in tri_contas]
    return rows
```

Atualizar a asserção do dicionário de stats em `test_dre_publicado_nos_tres_primeiros_e_4t_derivado`, que passa a ter a chave nova:

```python
    assert stats["DRE"] == {"exercicios": 1, "trimestres": 4, "linhas": 8, "docs_irregulares": 0,
                            "reapresentacao_intra_ano": 0, "componente_reapresentado": 0, "linha_sem_par": 0,
                            "par_ambiguo": 0, "sem_anterior": 0, "sem_3t": 0, "sem_dfp": 0}
```

Acrescentar ao final do arquivo, antes da seção `# ── main()`:

```python
# ── casamento de linhas entre os dois acumulados ─────────────────────────────

# Multiplan, DFC, 2026: a empresa reordena os códigos do bloco 6.03 entre o 1T e o 2T.
MULT_1T = {"6.03": ("Caixa Líquido Atividades de Financiamento", -317.0e6),
           "6.03.06": ("Pagamento de encargos e debêntures", -144.9e6),
           "6.03.08": ("Dividendos e juros sobre capital próprio", -97.5e6)}
MULT_2T = {"6.03": ("Caixa Líquido Atividades de Financiamento", -967.3e6),
           "6.03.06": ("Pagamento de debêntures", -175.0e6),
           "6.03.08": ("Pagamento de encargos sobre debêntures", -347.0e6),
           "6.03.09": ("Dividendos e juros sobre o capital prórpio", -203.4e6)}


def _mult(contas_1t=None, contas_2t=None):
    return _df(_doc("ITR", "2026-03-31", "Último", "2026-01-01", "2026-03-31", contas_1t or MULT_1T, "DFC_MI", st="N"),
               _doc("ITR", "2026-06-30", "Último", "2026-01-01", "2026-06-30", contas_2t or MULT_2T, "DFC_MI", st="N"))


def test_renumeracao_nao_mistura_encargos_de_debentures_com_dividendos():
    rows, flags, stats = dq.derive_quarters(_mult())
    q2 = {r["cd_conta"]: r for r in rows if r["trimestre"] == 2}
    # 6.03.08 no 2T é a linha que era 6.03.06 no 1T: −347,0 − (−144,9)
    r = q2["6.03.08"]
    assert (round(r["vl_derivado"] / 1e6, 1), r["cd_conta_b"], r["casamento"], r["flag"]) == (-202.1, "6.03.06", "reformulacao", None)
    # 6.03.09 no 2T é a linha que era 6.03.08 no 1T: −203,4 − (−97,5)
    r = q2["6.03.09"]
    assert (round(r["vl_derivado"] / 1e6, 1), r["cd_conta_b"], r["casamento"], r["flag"]) == (-105.9, "6.03.08", "reformulacao", None)
    # 6.03.06 no 2T ("Pagamento de debêntures") é linha nova: não deriva contra os encargos do 1T
    r = q2["6.03.06"]
    assert (r["vl_derivado"], r["vl_final"], r["cd_conta_b"], r["casamento"], r["flag"]) == (None, None, None, None, "linha_sem_par")
    assert stats["DFC_MI"]["linha_sem_par"] == 1 and stats["DFC_MI"]["par_ambiguo"] == 0


def test_par_ambiguo_nao_deriva_e_vira_fila_de_revisao():
    rows, flags, _ = dq.derive_quarters(_mult({"6.03": ("Financiamento", 100e6), "6.03.09": ("Captação de debêntures", 482.8e6)},
                                              {"6.03": ("Financiamento", 100e6), "6.03.12": ("Emissão de debêntures", 482.8e6)}))
    r = {x["cd_conta"]: x for x in rows if x["trimestre"] == 2}["6.03.12"]
    assert (r["vl_derivado"], r["vl_final"], r["origem"]) == (None, None, "derivado")
    assert (r["cd_conta_b"], r["casamento"], r["flag"]) == ("6.03.09", "ambiguo", "par_ambiguo")
    f, = [x for x in flags if x["classificacao"] == "par_ambiguo"]
    assert (f["layer"], f["check_type"], f["severity"], f["tipo_doc"], f["cd_conta"]) == (6, "derive_quarters", "warn", "DFC_MI", "6.03.12")
    assert (f["fonte_ref"], f["data_ref"], f["fonte_cmp"], f["data_cmp"]) == ("ITR", "2026-06-30", "ITR", "2026-03-31")
    assert (f["valor_ref"], f["valor_cmp"]) == (482.8e6, 482.8e6)
    assert (f["detalhe"]["cd_conta_b"], f["detalhe"]["ds_conta_b"]) == ("6.03.09", "Captação de debêntures")
    assert 0.55 < f["detalhe"]["score"] < 0.75


def test_mesmo_codigo_com_texto_retocado_continua_derivando():
    r = {x["cd_conta"]: x for x in dq.derive_quarters(_mult(
        {"6.03": ("Financiamento", 10e6), "6.03.01": ("Pagamento de emprestimos", 30e6)},
        {"6.03": ("Financiamento", 25e6), "6.03.01": ("Pagamento de empréstimos", 50e6)}))[0] if x["trimestre"] == 2}
    assert (r["6.03.01"]["vl_derivado"], r["6.03.01"]["cd_conta_b"], r["6.03.01"]["casamento"]) == (20e6, "6.03.01", "estavel")


def test_4t_casa_o_layout_do_dfp_com_o_do_itr_do_3t():
    itr3 = {"6.03": ("Financiamento", -430.0e6), "6.03.06": ("Dividendos e juros sobre o capital próprio pagos", -316.4e6),
            "6.03.07": ("Gastos com operações de ações", -0.1e6), "6.03.08": ("Pagamento de encargos sobre debêntures", -352.5e6)}
    dfp = {"6.03": ("Financiamento", -860.9e6), "6.03.07": ("Pagamento de encargos sobre debêntures", -560.1e6),
           "6.03.08": ("Aumento de capital social", 0.0), "6.03.09": ("Gastos com operações de ações", -0.1e6),
           "6.03.11": ("Dividendos pagos e juros sobre capital próprio", -492.0e6)}
    rows, _, _ = dq.derive_quarters(_df(
        _doc("ITR", "2025-03-31", "Último", "2025-01-01", "2025-03-31", {"6.03": ("Financiamento", -100e6)}, "DFC_MI", st="N"),
        _doc("ITR", "2025-06-30", "Último", "2025-01-01", "2025-06-30", {"6.03": ("Financiamento", -200e6)}, "DFC_MI", st="N"),
        _doc("ITR", "2025-09-30", "Último", "2025-01-01", "2025-09-30", itr3, "DFC_MI", st="N"),
        _doc("DFP", "2025-12-31", "Último", "2025-01-01", "2025-12-31", dfp, "DFC_MI", st="N")))
    q4 = {r["cd_conta"]: r for r in rows if r["trimestre"] == 4}
    assert (round(q4["6.03.07"]["vl_derivado"] / 1e6, 1), q4["6.03.07"]["cd_conta_b"]) == (-207.6, "6.03.08")
    assert (round(q4["6.03.11"]["vl_derivado"] / 1e6, 1), q4["6.03.11"]["cd_conta_b"]) == (-175.6, "6.03.06")
    assert (q4["6.03.09"]["vl_derivado"], q4["6.03.09"]["cd_conta_b"]) == (0.0, "6.03.07")
    # "Aumento de capital social" não existe no ITR do 3T: não pode virar o 4T dos encargos
    assert (q4["6.03.08"]["vl_derivado"], q4["6.03.08"]["flag"]) == (None, "linha_sem_par")


def test_primeiro_trimestre_nao_tem_casamento():
    r = {x["cd_conta"]: x for x in dq.derive_quarters(_mult())[0] if x["trimestre"] == 1}["6.03.08"]
    assert (r["cd_conta_b"], r["casamento"], r["vl_derivado"]) == (None, None, -97.5e6)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_derive_quarters.py -q 2>&1 | tail -8
```

Expected: 6 failed. As novas falham com `KeyError: 'cd_conta_b'` ou valores errados (`-249.5` em vez de `-202.1`), e `test_dre_publicado_nos_tres_primeiros_e_4t_derivado` passa a falhar só depois do Step 3 se a chave `par_ambiguo` não for adicionada às stats.

- [ ] **Step 3: Implementar**

Em `scripts/analysis/derive_quarters.py`:

Na docstring do módulo, trocar o parágrafo que vai de "Em cada documento, o acumulado" até a lista de flags por:

```
Em cada documento, o acumulado é a linha com menor dt_ini_exerc; o trimestre é a
duração do acumulado (3/6/9/12 meses → 1..4), o que também resolve exercício
social fora do calendário. Documento com outra duração (ou DFP que não é o 4T)
é irregular e não entra.

As linhas dos dois acumulados são casadas por check_text_stability.match_filings
(a escada da Camada 5: código fixo da CVM, nome normalizado, similaridade), nunca
pelo cd_conta puro — a empresa renumera as contas que cria (st_conta_fixa = 'N')
entre trimestres, e o DFP usa um layout diferente do ITR. cd_conta_b e casamento
registram qual linha do filing B foi subtraída e como ela foi encontrada.
Par 'ambiguo' (0,55 < score < 0,75) NÃO é casado automaticamente: vira fila de
revisão (decisão do usuário em 2026-09-18).

Por exercício (exercicio_ini) e trimestre n:
  - vl_publicado : DRE 1T–3T, linha trimestral isolada do ITR (dt_ini = início do trimestre)
  - vl_derivado  : n = 1 → acum(1T); n > 1 → acum(Qn) − acum(Qn−1) pela linha casada;
                   n = 4 → DFP − acum(3T)
  - vl_final     : publicado quando existe (origem 'publicado'), senão derivado
Flags (uma por linha; precedência nesta ordem):
  - 'reapresentacao_intra_ano' (warn): |publicado − derivado| > tolerância; na DFC,
    6.05 derivado do 4T ≠ variação do saldo final (6.05.02 DFP − 6.05.02 3T; reserva:
    BPA 1.01.01 na safra original) — também vira flag de linha em consistency_flags
  - 'linha_sem_par' (info): a linha não tem correspondente no acumulado anterior
  - 'par_ambiguo' (warn): o único candidato tem similaridade na faixa ambígua; não
    deriva e vira flag de linha em consistency_flags com o candidato e o score
  - 'sem_anterior' / 'sem_3t' (info): não há acumulado anterior (2T/3T; 4T)
  - 'componente_reapresentado' (info): minuendo ou subtraendo aparece num resumo
    'reapresentacao' da Camada 2 (consistency_flags layer 2)
  - 'sem_dfp': 3T sem DFP — só flag-resumo em consistency_flags (não há linha de 4T)
```

Trocar o bloco de imports e constantes:

```python
from check_text_stability import SIM_ALTO, SIM_BAIXO, match_filings
from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows, new_run,
                               parent_code, tolerancia, write_flags)

LAYER = 6
CHECK_TYPE = "derive_quarters"
TIPOS = ["DRE", "DFC_MI", "DVA"]
SAFRAS = {"original": "Último", "reapresentado": "Penúltimo"}
SEVERITY = {"reapresentacao_intra_ano": "warn", "componente_reapresentado": "info", "linha_sem_par": "info",
            "par_ambiguo": "warn", "sem_anterior": "info", "sem_3t": "info", "sem_dfp": "info"}
SKIP_PREFIX = "3.99"
COLS = ["run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
        "cd_conta", "ds_conta", "cd_conta_b", "casamento", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
        "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"]
```

Em `docs_acumulados`, guardar também `st_conta_fixa`. Trocar a docstring e a linha do `acum`:

```python
    doc = {"fonte", "data", "ordem", "ini", "fim", "acum": {cd: (ds, vl, st)}, "tri": {cd: vl}} — tri só
    tem as linhas de período curto (dt_ini > exercicio_ini), i.e. o trimestre isolado da DRE."""
```

```python
                acum.setdefault(r.cd_conta, (_texto(r.ds_conta), r.vl_conta, _texto(r.st_conta_fixa)))
```

`_saldo_caixa` continua correto: `doc["acum"]["6.05.02"][1]` segue sendo o valor.

Acrescentar, logo depois de `_flag_linha`:

```python
def _flag_ambiguo(cnpj, tipo_doc, cd, ds, ini_q, fim_q, a, b, cd_b, score, detalhe) -> dict:
    """Fila de revisão: o único candidato a par está na faixa ambígua de similaridade."""
    return {
        "layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "par_ambiguo", "severity": "warn",
        "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": cd, "cd_conta_pai": parent_code(cd), "ds_conta": ds,
        "periodo_ini": ini_q, "periodo_fim": fim_q,
        "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
        "fonte_cmp": b["fonte"], "data_cmp": b["data"], "ordem_cmp": b["ordem"],
        "valor_ref": _valor(a["acum"][cd][1]), "valor_cmp": _valor(b["acum"][cd_b][1]),
        "detalhe": {**detalhe, "cd_conta_b": cd_b, "ds_conta_b": b["acum"][cd_b][0], "score": score},
    }


def _casar(a: dict, b: dict | None, sim_alto: float, sim_baixo: float) -> dict:
    """{cd no acumulado atual: (cd no anterior, classe, score)}; vazio quando não há anterior."""
    if b is None:
        return {}
    return match_filings({cd: (ds, st) for cd, (ds, _vl, st) in b["acum"].items()},
                         {cd: (ds, st) for cd, (ds, _vl, st) in a["acum"].items()},
                         sim_alto, sim_baixo)
```

Trocar a assinatura de `_derivar_exercicio` e o laço das contas:

```python
def _derivar_exercicio(cnpj, tipo_doc, safra, exercicio_ini, qs: dict, bpa: dict, reapresentados: set,
                       tol_abs, tol_rel, sim_alto, sim_baixo) -> tuple[list[dict], list[dict], dict]:
```

```python
        linhas_q: list[dict] = []
        casar = _casar(a, b, sim_alto, sim_baixo) if not falta else {}
        for cd, (ds, va, _st) in a["acum"].items():
            cd_b = casamento = None
            if n == 1:
                pub = _valor(va) if tipo_doc == "DRE" else None
                der = _valor(va)
                flag = None
            else:
                pub = _valor(a["tri"][cd]) if tipo_doc == "DRE" and n < 4 and cd in a["tri"] else None
                par = casar.get(cd)
                if falta:
                    der, flag = None, falta
                elif par is None:
                    der, flag = None, "linha_sem_par"
                else:
                    cd_b, casamento, score = par
                    if casamento == "ambiguo":
                        der, flag = None, "par_ambiguo"
                        flags.append(_flag_ambiguo(cnpj, tipo_doc, cd, ds, ini_q, fim_q, a, b, cd_b, score, detalhe))
                    else:
                        der, flag = _valor(va) - _valor(b["acum"][cd_b][1]), None
            if pub is not None and der is not None and abs(pub - der) > tolerancia(pub, tol_abs, tol_rel):
                flag = "reapresentacao_intra_ano"
                flags.append(_flag_linha(cnpj, tipo_doc, cd, ds, ini_q, fim_q, a, b, pub, der, detalhe))
            elif flag is None and componente:
                flag = "componente_reapresentado"
            linhas_q.append({**base, "cd_conta": cd, "ds_conta": ds, "cd_conta_b": cd_b, "casamento": casamento,
                             "vl_publicado": pub, "vl_derivado": der,
                             "origem": "publicado" if pub is not None else "derivado",
                             "vl_final": pub if pub is not None else der, "flag": flag})
```

Trocar a assinatura e a chamada em `derive_quarters`:

```python
def derive_quarters(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01,
                    reapresentados: set | None = None, sim_alto: float = SIM_ALTO,
                    sim_baixo: float = SIM_BAIXO) -> tuple[list[dict], list[dict], dict]:
```

```python
                    r, f, cont = _derivar_exercicio(cnpj, tipo_doc, safra, exercicio_ini, qs, bpa, reapresentados,
                                                    tol_abs, tol_rel, sim_alto, sim_baixo)
```

Em `main`, acrescentar os dois argumentos depois de `add_common_args(parser)`:

```python
    parser.add_argument("--sim-alto", dest="sim_alto", type=float, default=SIM_ALTO,
                        help="score mínimo para casar como 'reformulacao' (padrão 0.75)")
    parser.add_argument("--sim-baixo", dest="sim_baixo", type=float, default=SIM_BAIXO,
                        help="score máximo para tratar como linha sem par (padrão 0.55); entre os dois é 'par_ambiguo', que não deriva")
```

trocar a linha do `print` de abertura:

```python
    print(f"run {run_id}: {len(cnpjs)} empresa(s), tol_abs={args.tol_abs} tol_rel={args.tol_rel} "
          f"sim_alto={args.sim_alto} sim_baixo={args.sim_baixo}")
```

e a chamada de `derive_quarters`:

```python
        rows, flags, stats = derive_quarters(df, args.tol_abs, args.tol_rel, reapresentados_camada2(conn, cnpj),
                                             args.sim_alto, args.sim_baixo)
```

Por fim, atualizar o bloco de uso no rodapé da docstring do módulo:

```
Roda no job semanal (scripts/update_weekly.sh) depois da Camada 5. À mão
(na pasta scripts/analysis, .venv ativo):
  python derive_quarters.py --cnpj 84.429.695/0001-11
  python derive_quarters.py --cnpj 84.429.695/0001-11 --tipo-doc DRE --desde 2020
  python derive_quarters.py --full               # base inteira (~145 empresas)
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 171 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add scripts/analysis/derive_quarters.py tests/test_derive_quarters.py && git commit -q -m "fix(analysis): Camada 6 subtrai a linha casada, não o mesmo cd_conta" && git log --oneline -1
```

---

### Task 4: Validação contra o dado bruto real (2017, 2021, 2025)

Testes que leem `cvm_research.db`. Pulam quando o banco não existe, então o `pytest tests/` de uma máquina limpa continua verde.

**Files:**
- Create: `tests/test_derive_quarters_real.py`

- [ ] **Step 1: Escrever os testes**

```python
"""
Validação da Camada 6 contra o dado bruto da CVM no banco de produção.

Os testes de tests/test_derive_quarters.py usam documentos sintéticos; estes leem
cvm_research.db e conferem, filing a filing, que cada trimestre derivado sai de duas
linhas que são de fato a mesma linha e que a conta fecha. Anos distantes de propósito
(2017, 2021, 2025): o layout das contas criadas pela empresa muda muito ao longo da série.

Pulados quando o banco não está presente (CI, clone novo). Para rodar:
  cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_derive_quarters_real.py -q
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

from consistency_utils import normalize_text, parent_code, text_similarity

DB = os.environ.get("CVM_DB", os.path.join(os.path.dirname(__file__), "..", "cvm_research.db"))
ANOS = ("2017", "2021", "2025")
# Mistura de perfis: renumeração pesada (MULT3, EQTL3), plano COSIF (ITUB4),
# layout estável (WEGE3) e duas grandes com muitas sublinhas (VALE3, PETR4).
TICKERS = ("MULT3", "EQTL3", "ITUB4", "WEGE3", "VALE3", "PETR4")
MULT = "07.816.890/0001-53"

pytestmark = pytest.mark.skipif(not os.path.exists(DB), reason=f"banco de produção ausente em {DB}")


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def cnpjs(conn):
    achados = {t: c for t, c in conn.execute(
        f"SELECT ticker, cnpj FROM companies WHERE ticker IN ({','.join('?' * len(TICKERS))})", TICKERS)}
    faltando = [t for t in TICKERS if t not in achados]
    assert not faltando, f"tickers fora da watchlist: {faltando}"
    return achados


def _derivadas(conn, cnpj):
    """Linhas de demonstrativos_trimestrais com valor derivado nos anos de interesse."""
    return conn.execute(f"""
        SELECT tipo_doc, safra, exercicio_ini, trimestre, cd_conta, ds_conta, cd_conta_b, casamento,
               vl_derivado, fonte_a, data_a, ordem_a, fonte_b, data_b, ordem_b
        FROM demonstrativos_trimestrais
        WHERE cnpj_companhia = ? AND trimestre > 1 AND vl_derivado IS NOT NULL
          AND substr(dt_fim_exerc, 1, 4) IN ({','.join('?' * len(ANOS))})
        ORDER BY tipo_doc, safra, exercicio_ini, trimestre, cd_conta""", (cnpj, *ANOS)).fetchall()


def _acumulado(conn, cnpj, tipo_doc, fonte, data_ref, ordem):
    """{cd_conta: (ds_conta, vl_conta)} do acumulado (menor dt_ini_exerc) de um filing,
    na versão máxima — o mesmo recorte que consistency_utils.latest_rows faz."""
    linhas = conn.execute("""
        SELECT cd_conta, ds_conta, vl_conta, dt_ini_exerc FROM demonstrativos_contabeis
        WHERE cnpj_companhia = ? AND tipo_doc = ? AND fonte = ? AND data_referencia = ? AND ordem_exercicio = ?
          AND versao = (SELECT MAX(versao) FROM demonstrativos_contabeis
                        WHERE cnpj_companhia = ? AND tipo_doc = ? AND fonte = ? AND data_referencia = ?)
        """, (cnpj, tipo_doc, fonte, data_ref, ordem, cnpj, tipo_doc, fonte, data_ref)).fetchall()
    inicios = [r[3] for r in linhas if r[3] is not None]
    if not inicios:
        return {}
    ini = min(inicios)
    out = {}
    for cd, ds, vl, dt_ini in linhas:
        if dt_ini == ini:
            out.setdefault(cd, (ds, vl))
    return out


def test_todo_derivado_bate_com_a_subtracao_do_bruto(conn, cnpjs):
    """vl_derivado == vl_conta(A, cd_conta) − vl_conta(B, cd_conta_b), lido do dado bruto."""
    conferidas = 0
    erros = []
    for ticker, cnpj in cnpjs.items():
        cache = {}
        for r in _derivadas(conn, cnpj):
            (tipo, _safra, _ex, tri, cd, _ds, cd_b, casamento, vl, fa, da, oa, fb, db, ob) = r
            assert cd_b and casamento, f"{ticker} {tipo} {da} {cd}: derivou sem registrar o par"
            for chave in ((tipo, fa, da, oa), (tipo, fb, db, ob)):
                if chave not in cache:
                    cache[chave] = _acumulado(conn, cnpj, *chave)
            va = cache[(tipo, fa, da, oa)].get(cd)
            vb = cache[(tipo, fb, db, ob)].get(cd_b)
            assert va and vb, f"{ticker} {tipo} {da} {cd}: par {cd_b} não está no bruto"
            esperado = (va[1] or 0.0) - (vb[1] or 0.0)
            if abs(vl - esperado) > 0.01:
                erros.append(f"{ticker} {tipo} {da} T{tri} {cd}: gravado {vl:,.2f} ≠ bruto {esperado:,.2f}")
            conferidas += 1
    assert not erros, "\n".join(erros[:20])
    assert conferidas > 5000, f"amostra pequena demais ({conferidas} linhas): a Camada 6 rodou?"


def test_nenhum_derivado_casa_linhas_de_conteudo_diferente(conn, cnpjs):
    """A regressão original: subtrair 'Dividendos' de 'Pagamento de encargos'.
    Todo par usado tem nome igual (normalizado) ou similaridade >= 0.75."""
    erros = []
    for ticker, cnpj in cnpjs.items():
        cache = {}
        for r in _derivadas(conn, cnpj):
            (tipo, _safra, _ex, _tri, cd, ds, cd_b, casamento, _vl, _fa, da, _oa, fb, db, ob) = r
            assert casamento != "ambiguo", f"{ticker} {tipo} {da} {cd}: par ambíguo não pode derivar"
            if (tipo, fb, db, ob) not in cache:
                cache[(tipo, fb, db, ob)] = _acumulado(conn, cnpj, tipo, fb, db, ob)
            ds_b = cache[(tipo, fb, db, ob)][cd_b][0]
            if normalize_text(ds) == normalize_text(ds_b):
                continue
            score = text_similarity(ds, ds_b)
            if score < 0.75:
                erros.append(f"{ticker} {tipo} {da} {cd} '{ds}' ← {cd_b} '{ds_b}' (score {score:.2f}, casamento {casamento})")
    assert not erros, f"{len(erros)} pares de conteúdo diferente:\n" + "\n".join(erros[:20])


def test_oraculo_independente_por_nome_unico(conn, cnpjs):
    """Checagem sem usar a escada de similaridade: quando um nome normalizado é único
    nos dois acumulados E está sob o mesmo pai, o subtraendo correto é inequívoco.
    A Camada 6 tem de concordar. O recorte pelo pai é necessário porque o casamento é
    hierárquico: um pai renumerado leva os filhos junto, e aí o código do pai muda dos
    dois lados — nesses casos o oráculo não se aplica e a linha é pulada."""
    conferidas = 0
    erros = []
    for ticker, cnpj in cnpjs.items():
        cache = {}
        for r in _derivadas(conn, cnpj):
            (tipo, _safra, _ex, _tri, cd, ds, cd_b, _cas, _vl, fa, da, oa, fb, db, ob) = r
            for chave in ((tipo, fa, da, oa), (tipo, fb, db, ob)):
                if chave not in cache:
                    cache[chave] = _acumulado(conn, cnpj, *chave)
            alvo = normalize_text(ds)
            if not alvo:
                continue
            em_a = [c for c, (d, _v) in cache[(tipo, fa, da, oa)].items() if normalize_text(d) == alvo]
            em_b = [c for c, (d, _v) in cache[(tipo, fb, db, ob)].items()
                    if normalize_text(d) == alvo and parent_code(c) == parent_code(cd)]
            if len(em_a) != 1 or len(em_b) != 1:
                continue                                   # nome repetido, ausente ou pai diferente
            if em_b[0] != cd_b:
                erros.append(f"{ticker} {tipo} {da} {cd} '{ds}': casou com {cd_b}, nome único aponta {em_b[0]}")
            conferidas += 1
    assert not erros, f"{len(erros)} divergências do oráculo:\n" + "\n".join(erros[:20])
    assert conferidas > 3000, f"oráculo cobriu pouco ({conferidas} linhas)"


def test_multiplan_6_03_08_regressao_relatada(conn):
    """O caso que originou a correção: 6.03.08 da DFC virou dividendo no 1T e encargos
    de debêntures no 2T, e o DFP manteve 'Aumento de capital social' no mesmo código."""
    q = dict(((r[0], r[1]), r[2:]) for r in conn.execute("""
        SELECT trimestre, cd_conta, ds_conta, cd_conta_b, casamento, vl_derivado, vl_final, flag
        FROM demonstrativos_trimestrais
        WHERE cnpj_companhia = ? AND tipo_doc = 'DFC_MI' AND safra = 'original'
          AND exercicio_ini = '2026-01-01' AND cd_conta LIKE '6.03.%'""", (MULT,)))
    ds, cd_b, cas, vl, final, flag = q[(2, "6.03.08")]
    assert ds == "Pagamento de encargos sobre debêntures"
    assert (cd_b, cas, flag) == ("6.03.06", "reformulacao", None)
    assert round(final / 1e6, 1) == -202.1                 # −347,0 − (−144,9); antes gravava −249,5
    ds, cd_b, cas, vl, final, flag = q[(2, "6.03.09")]
    assert (cd_b, cas) == ("6.03.08", "reformulacao") and round(final / 1e6, 1) == -105.9
    ds, cd_b, cas, vl, final, flag = q[(2, "6.03.06")]                 # "Pagamento de debêntures" é linha nova
    assert (ds, vl, final, flag) == ("Pagamento de debêntures", None, None, "linha_sem_par")

    q25 = dict(((r[0], r[1]), r[2:]) for r in conn.execute("""
        SELECT trimestre, cd_conta, ds_conta, cd_conta_b, casamento, vl_derivado, vl_final, flag
        FROM demonstrativos_trimestrais
        WHERE cnpj_companhia = ? AND tipo_doc = 'DFC_MI' AND safra = 'original'
          AND exercicio_ini = '2025-01-01' AND trimestre = 4 AND cd_conta LIKE '6.03.%'""", (MULT,)))
    ds, cd_b, cas, vl, final, flag = q25[(4, "6.03.07")]
    assert (ds, cd_b, cas) == ("Pagamento de encargos sobre debêntures", "6.03.08", "renumerado")
    assert round(final / 1e6, 1) == -207.6                 # −560,1 − (−352,5)
    ds, cd_b, cas, vl, final, flag = q25[(4, "6.03.08")]
    assert ds == "Aumento de capital social"
    assert (vl, final, flag) == (None, None, "linha_sem_par")   # antes gravava +352,5


def test_par_ambiguo_e_fila_de_revisao_nao_valor(conn):
    """Nenhum 'par_ambiguo' tem valor, e cada um deixa o candidato registrado."""
    assert conn.execute("""SELECT COUNT(*) FROM demonstrativos_trimestrais
                           WHERE flag = 'par_ambiguo' AND vl_derivado IS NOT NULL""").fetchone()[0] == 0
    n_linhas = conn.execute("SELECT COUNT(*) FROM demonstrativos_trimestrais WHERE flag = 'par_ambiguo'").fetchone()[0]
    n_flags = conn.execute("""SELECT COUNT(*) FROM consistency_flags
                              WHERE layer = 6 AND classificacao = 'par_ambiguo'""").fetchone()[0]
    assert n_linhas == n_flags > 0
    faltando = conn.execute("""SELECT COUNT(*) FROM consistency_flags WHERE layer = 6 AND classificacao = 'par_ambiguo'
                               AND (json_extract(detalhe, '$.cd_conta_b') IS NULL
                                    OR json_extract(detalhe, '$.score') IS NULL)""").fetchone()[0]
    assert faltando == 0
```

- [ ] **Step 2: Rodar contra a base atual e ver falhar**

Ainda sem a migração e sem o re-run, as colunas novas não existem.

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_derive_quarters_real.py -q 2>&1 | tail -6
```

Expected: 5 failed com `sqlite3.OperationalError: no such column: cd_conta_b`. Isso confirma que os testes leem mesmo o banco de produção.

- [ ] **Step 3: Aplicar a migração e regerar a Camada 6 das empresas da amostra**

O primeiro comando esvazia `demonstrativos_trimestrais` na base inteira; a tabela só volta a ficar completa na Task 5. Não é preciso backup: a tabela é 100% derivada de `demonstrativos_contabeis`, que não é tocada, e o conteúdo descartado estava errado.

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 cvm_research.db "SELECT COUNT(*) AS antes FROM demonstrativos_trimestrais" && sqlite3 cvm_research.db < scripts/migrations/2026-09-18_trimestrais_casamento.sql && sqlite3 cvm_research.db < schema.sql && sqlite3 cvm_research.db "SELECT COUNT(*) AS depois FROM demonstrativos_trimestrais"
```

Expected: `antes` = 1797994 e `depois` = 0.

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && for T in MULT3 EQTL3 ITUB4 WEGE3 VALE3 PETR4; do C=$(sqlite3 ../../cvm_research.db "SELECT cnpj FROM companies WHERE ticker='$T'"); ../../.venv/bin/python derive_quarters.py --cnpj "$C" | tail -2; done
```

Expected: seis blocos `total_checked=... total_flagged=...`, cada um com dezenas de milhares de linhas trimestrais.

- [ ] **Step 4: Rodar os testes reais e ver passar**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_derive_quarters_real.py -q 2>&1 | tail -6
```

Expected: 5 passed.

Se `test_nenhum_derivado_casa_linhas_de_conteudo_diferente` falhar, é bug real de casamento: investigar os pares listados antes de seguir, não afrouxar o limiar.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add tests/test_derive_quarters_real.py && git commit -q -m "test(analysis): validação da Camada 6 contra o bruto real em 2017, 2021 e 2025" && git log --oneline -1
```

---

### Task 5: Re-run completo e medição do efeito

**Files:** nenhum (execução e medição)

- [ ] **Step 1: Rodar a Camada 6 na base inteira**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research/scripts/analysis && time ../../.venv/bin/python run_all.py --layer 6 --full 2>&1 | tail -8
```

Expected: `Resumo por tipo_doc` com as três linhas (DRE, DFC_MI, DVA) e a chave `par_ambiguo` preenchida. Tempo esperado entre 3 e 6 minutos (antes eram 76 s; o casamento acrescenta uma passada de similaridade por par de filings, na mesma ordem de grandeza dos ~100 s da Camada 5). Se passar de 15 minutos, medir antes de otimizar.

- [ ] **Step 2: Medir o que mudou**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -header -column cvm_research.db "
SELECT tipo_doc, trimestre,
       COUNT(*) AS linhas,
       SUM(vl_final IS NOT NULL) AS com_valor,
       SUM(casamento = 'estavel')      AS mesmo_codigo,
       SUM(casamento = 'renumerado')   AS renumerado,
       SUM(casamento = 'reformulacao') AS reformulacao,
       SUM(flag = 'par_ambiguo')       AS ambiguo_bloqueado,
       SUM(flag = 'linha_sem_par')     AS sem_par
FROM demonstrativos_trimestrais WHERE safra='original' AND trimestre > 1
GROUP BY 1,2 ORDER BY 1,2;"
```

Registrar a saída no README (Task 6). Critérios de aceitação:

1. `renumerado + reformulacao` na DFC do 4T tem de ficar na casa dos milhares: é a massa que antes era subtraída errado.
2. `com_valor` na DFC cai em relação aos 84% de antes. Isso é esperado e desejado: linhas que não existem no acumulado anterior agora são NULL em vez de um número inventado.
3. `ambiguo_bloqueado` maior que zero e bem menor que `renumerado`.

- [ ] **Step 3: Conferir que a suíte inteira passa contra a base regerada**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 176 passed (171 sintéticos + 5 reais).

- [ ] **Step 4: Conferir a fila de revisão dos ambíguos**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && sqlite3 -header -column cvm_research.db "
SELECT c.ticker, f.tipo_doc, f.data_ref, f.cd_conta, substr(f.ds_conta,1,34) AS linha,
       json_extract(f.detalhe,'\$.cd_conta_b') AS cd_b,
       substr(json_extract(f.detalhe,'\$.ds_conta_b'),1,34) AS candidato,
       ROUND(json_extract(f.detalhe,'\$.score'),3) AS score
FROM consistency_flags f JOIN companies c ON c.cnpj = f.cnpj_companhia
WHERE f.layer = 6 AND f.classificacao = 'par_ambiguo'
ORDER BY score DESC LIMIT 25;"
```

Expected: uma lista de pares plausíveis com score entre 0,55 e 0,75. Não é um erro: é a fila que o usuário pediu para não casar sozinho.

- [ ] **Step 5: Commit**

Nada a commitar neste passo (só dados). Seguir para a Task 6.

---

### Task 6: Documentação

**Files:**
- Modify: `CLAUDE.md` (seções `demonstrativos_trimestrais`, `consistency_flags`, "Comportamento esperado ao pesquisar" item 12, query de exemplo da Camada 6)
- Modify: `README.md` (histórico/medições)

- [ ] **Step 1: Atualizar a descrição da tabela no CLAUDE.md**

Trocar o bloco `### demonstrativos_trimestrais ...` por:

```markdown
### `demonstrativos_trimestrais` — valor de cada trimestre da DRE/DFC_MI/DVA, por conta e por safra (Camada 6)
`run_id, cnpj_companhia, tipo_doc ('DRE'/'DFC_MI'/'DVA'), safra ('original'/'reapresentado'), exercicio_ini, dt_ini_exerc, dt_fim_exerc,`
`trimestre (1–4, posição no exercício social), cd_conta, ds_conta, cd_conta_b, casamento, vl_publicado, vl_derivado,`
`origem ('publicado'/'derivado'), vl_final, flag,`
`fonte_a, data_a, ordem_a (filing do acumulado do trimestre), fonte_b, data_b, ordem_b (filing do acumulado anterior; NULL no 1T)`

**Use `vl_final`** (e `origem` para saber de onde veio). `safra = 'original'` usa só colunas `Último` (o que o mercado viu na época);
`'reapresentado'` usa só colunas `Penúltimo` dos filings do exercício seguinte. **Nunca subtrai safras diferentes.**
- DRE 1T–3T: `vl_publicado` é a linha trimestral isolada do ITR (`origem = 'publicado'`); `vl_derivado = acum(Qn) − acum(Qn−1)` serve de conferência.
- DRE 4T, DFC_MI e DVA (todos os trimestres): só derivado (`4T = DFP − acum(3T)`).
- **`cd_conta_b` e `casamento`**: qual linha do filing anterior foi subtraída e como ela foi encontrada. A empresa renumera
  as contas que cria (`st_conta_fixa = 'N'`) entre trimestres, e o DFP usa um layout diferente do ITR, então o mesmo `cd_conta`
  costuma ser outra linha no filing anterior. O casamento usa a escada da Camada 5: `estavel` (mesmo código, contas `S` ou
  mesmo nome), `renumerado` (mesmo nome normalizado, código diferente), `reformulacao` (similaridade ≥ 0,75).
  Para auditar um número, compare `cd_conta` (filing A) com `cd_conta_b` (filing B) no dado bruto.
- `flag`: `reapresentacao_intra_ano` (publicado ≠ derivado, ou 6.05 do 4T da DFC ≠ variação do saldo final de caixa; também em `consistency_flags` `layer = 6`),
  `par_ambiguo` (o único candidato a par tem similaridade entre 0,55 e 0,75 — não deriva, e a flag de linha em `consistency_flags`
  traz `cd_conta_b`, `ds_conta_b` e `score` para revisão), `linha_sem_par` (a linha não existe no acumulado anterior — `vl_derivado` NULL),
  `sem_anterior`/`sem_3t` (buraco na série — NULL), `componente_reapresentado` (um dos dois filings tem `reapresentacao` na Camada 2).
  `sem_dfp` só em `consistency_flags` (não há linha de 4T).
- `3.99` (lucro por ação) não está na tabela: não é aditivo. Exercício social fora do calendário: `trimestre` é a posição no exercício, não o trimestre-calendário.
Para rodar: `run_all.py --layer 6 --cnpj <CNPJ>` (depende da Camada 2 já executada).
```

- [ ] **Step 2: Atualizar a query de exemplo e o item 12**

No CLAUDE.md, na seção "Série trimestral com 4T derivado (Camada 6)", trocar a primeira query por:

```sql
-- Receita e lucro por trimestre, safra original (o que o mercado viu), últimos 8 trimestres
SELECT exercicio_ini, trimestre, dt_ini_exerc, dt_fim_exerc,
       MAX(CASE WHEN cd_conta = '3.01' THEN vl_final END) AS receita,
       MAX(CASE WHEN cd_conta = '3.11' THEN vl_final END) AS lucro,
       MAX(CASE WHEN cd_conta = '3.01' THEN origem END)   AS origem_receita,
       GROUP_CONCAT(DISTINCT CASE WHEN cd_conta IN ('3.01','3.11') THEN flag END) AS flags
FROM demonstrativos_trimestrais
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DRE' AND safra = 'original'
GROUP BY 1, 2, 3, 4 ORDER BY dt_fim_exerc DESC LIMIT 8;

-- Auditar uma linha criada pela empresa: qual conta do filing anterior foi subtraída
SELECT dt_fim_exerc, trimestre, cd_conta, ds_conta, cd_conta_b, casamento,
       ROUND(vl_final/1e6, 1) AS vl_mi, flag,
       fonte_a || ' ' || data_a AS filing_a, fonte_b || ' ' || data_b AS filing_b
FROM demonstrativos_trimestrais
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DFC_MI' AND safra = 'original'
  AND cd_conta LIKE '6.03.%'
ORDER BY dt_fim_exerc DESC, cd_conta LIMIT 30;
```

E trocar o item 12 de "Comportamento esperado ao pesquisar" por:

```markdown
12. **Para valores trimestrais (4T da DRE, qualquer trimestre da DFC/DVA)**: use `demonstrativos_trimestrais` com
    `safra = 'original'` por padrão, nunca subtraia acumulados à mão misturando `Último` e `Penúltimo`. Mostre `origem` e a
    `flag`: `reapresentacao_intra_ano` significa que publicado e derivado divergem (apresente os dois); `linha_sem_par`/`sem_3t`
    significa que o trimestre não pôde ser derivado para aquela conta; `par_ambiguo` significa que a linha mudou de nome o
    bastante para o casamento ficar duvidoso e o valor foi deliberadamente não calculado (o candidato está no `detalhe` da
    flag `layer = 6`). Em contas criadas pela empresa (`st_conta_fixa = 'N'`), cite `cd_conta_b` e `casamento` ao apresentar
    o número: eles dizem qual linha do filing anterior entrou na subtração.
```

- [ ] **Step 3: Registrar a correção no README**

Acrescentar à seção "Histórico" do `README.md`, no topo da lista:

```markdown
- **18/09/2026 — casamento de linhas no desacúmulo (Camada 6).** A Camada 6 subtraía acumulados casando por `cd_conta`, que
  não é estável entre filings: 21% das linhas derivadas da DFC no 2T e no 3T e 39% no 4T subtraíam uma linha diferente, quase
  sempre sem flag (cerca de 24,6 mil valores errados só na DFC de 2T e 3T, em todas as 145 empresas). Passa a usar
  `match_filings`, a escada de casamento da Camada 5, e registra o par em `cd_conta_b`/`casamento`. Pares de similaridade
  ambígua (0,55 a 0,75) não são casados: viram `par_ambiguo`, fila de revisão. Plano e medições em
  `docs/superpowers/plans/2026-09-18-fase6-casamento-de-linhas-no-desacumulo.md`.
```

Acrescentar, no mesmo item, a tabela medida no Step 2 da Task 5.

- [ ] **Step 4: Conferir que nada quebrou**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 176 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/lucasbarreto/Documents/Coding/cvm-research && git add CLAUDE.md README.md docs/superpowers/plans/2026-09-18-fase6-casamento-de-linhas-no-desacumulo.md && git commit -q -m "docs: cd_conta_b/casamento e par_ambiguo na Camada 6" && git log --oneline -3
```

---

## O que a execução acrescentou ao plano (18/09/2026)

Os testes contra o dado bruto da Task 4 acharam duas coisas que o plano não previa. Ambas foram resolvidas dentro
da Task 4, antes do re-run completo.

**1. Contas `S` também são renumeradas — `codigo_fixo_confiavel`.** O passo 0 de `_comparar_pai` casa conta
`st_conta_fixa = 'S'` pelo código sem olhar o nome, porque o código é fixado pela CVM. Isso vale dentro de uma versão
do plano de contas, mas não entre versões. Na revisão do plano dos bancos, entre o ITR do 3T/2017 e o DFP/2017, o Itaú
teve a lista re-letrada:

| código | ITR 3T/2017 | DFP/2017 |
|---|---|---|
| 3.01.02 | Receita de Dividendos | Resultado de Operações de Câmbio |
| 3.01.03 | Resultado de Operações de Câmbio | Ganho (Perda) Líquido com Ativos e Passivos Financeiros |
| 3.04.05.01 | Outras Receitas | Resultado de Operações de Seg., Prev., Cap. |

Com o casamento por código a Camada 6 subtraía dividendos de câmbio: a mesma família de erro do bug relatado, só que no
plano `S`. `_comparar_pai`, `compare_filings` e `match_filings` ganharam `codigo_fixo_confiavel`. A Camada 5 mantém o
padrão `True` (a regra documentada no CLAUDE.md não muda); `match_filings` usa `False`, porque quem casa para fazer
conta não pode aceitar o código sem olhar o nome. Nome apenas retocado continua casando pela similaridade.

**2. `text_similarity` é assimétrica.** `difflib.SequenceMatcher(None, a, b).ratio()` não é simétrico, então
`text_similarity(x, y) ≠ text_similarity(y, x)` — em quatro pares reais a diferença cruzou o limiar de 0,75
(0,7532 contra 0,7273, por exemplo). Era bug do teste, que chamava na ordem inversa à de `_comparar_pai`; a ordem
correta é `(anterior, atual)`. Fica registrado como wart pré-existente da Camada 4: a classificação depende de qual
lado é o anterior. Tornar a função simétrica mudaria a Camada 5 inteira e está fora do escopo desta fase.

## Resultado medido (base inteira, 18/09/2026)

Run `--layer 6 --full` em 106 s, 1.797.994 linhas. A tabela por `tipo_doc` × trimestre está no README. Em resumo:

- `renumerado` + `reformulacao` somam 15.476 linhas no 2T da DFC, 14.554 no 3T e 27.147 no 4T. É a massa que antes
  era subtraída errado.
- Cobertura da DFC no 4T caiu de 84% para 78%: linha sem correspondente no acumulado anterior agora é NULL.
- `reapresentacao_intra_ano` na DRE caiu de 13.024 para 11.512. As 1.512 que sumiram eram artefato do casamento errado.
- Fila `par_ambiguo`: 14.993 flags, 57% no mesmo código. Amostra revista à mão contém julgamento genuíno, como
  "Perda / (ganho) na venda de propriedades para investimento" contra "Provisão para perda de investimentos e
  propriedades para investimento" (score 0,748), que são linhas diferentes e não devem ser subtraídas uma da outra.

## O que este plano deliberadamente NÃO faz

- **Não muda a Camada 5.** A trilha continua comparando só filings consecutivos da mesma fonte. `match_filings` é uma porta nova para a mesma escada, não um comportamento novo da Camada 5.
- **Não mexe em `demonstrativos_contabeis`.** O valor publicado pela CVM continua intacto; tudo aqui é metadado derivado.
- **Não tenta resolver os `par_ambiguo`.** Por decisão do usuário eles ficam como fila de revisão. Um passo futuro pode oferecer um comando para o analista confirmar ou rejeitar cada par.
- **Não revisita as Camadas 1, 2 e 3.** A Camada 2 compara o mesmo período entre filings, então não sofre do mesmo problema; a Camada 3 já casa por nome.
