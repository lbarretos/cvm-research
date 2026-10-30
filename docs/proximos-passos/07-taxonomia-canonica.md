# Etapa 7: Taxonomia canônica entre empresas (camada L2)

## Avaliação atual

As contas `N` são uma cauda longa, e a DFC concentra o problema:

| Demonstrativo | Linhas N | Nomes distintos | Usados por 1 só empresa | Em ≥10 empresas | Nomes p/ cobrir 80% das linhas | Jaccard entre empresas (DFP 2024) |
|---|---|---|---|---|---|---|
| BPA | 102 mil | 1.672 | 82% | 55 | 226 | — |
| BPP | 110 mil | 2.474 | 81% | 52 | 611 | 0,030 |
| DRE | 111 mil | 1.601 | 88% | 24 | 184 | 0,333 |
| **DFC** | **296 mil** | **15.536** | **88%** | 149 | **3.685** | **0,033** |
| DVA | 22 mil | 1.182 | 88% | 5 | 352 | — |

O modelo da CVM fixa a DFC só até o nível 3 (`6.01.01`, `6.01.02`, `6.02`, `6.03`). Tudo o que um
analista quer da DFC está em linhas `N`: D&A, capex, dividendos, juros, dívida, arrendamento e recompra.
No DFP 2024, 138 das 140 empresas do plano padrão abrem `6.01.01`, `6.01.02`, `6.02` e `6.03` em contas
próprias.

## Proposta

1. **Conceitos.** São 80–120, organizados em árvore e ancorados nos pais `S`. Os primeiros 30: DRE e
   balanço resumido (vêm direto de contas `S` pelo `plano_cvm` da Etapa 5) mais os 11 da DFC testados abaixo.
2. **Classificação das contas N em três passos:**
   - (a) **regras** (regex sobre o nome normalizado + prefixo do pai + exclusões + sinal esperado);
   - (b) **modelo supervisionado** (TF-IDF de n-gramas de caracteres + pai + sinal, regressão logística)
     treinado nos rótulos das regras;
   - (c) **revisão humana** das discordâncias entre (a) e (b), com prioridade para confiança alta e
     materialidade alta.

   A decisão é gravada por **linha econômica** (Etapa 6), não por filing.
3. **Publicação só com checagem.** Tabela `fato_padronizado(cnpj, fonte, periodo, safra, conceito, valor,
   n_linhas, metodo ('S'|'regra'|'modelo'|'humano'), confianca, checagem)`. Um conceito só é publicado
   se passar pelas identidades:

| Identidade | Valida |
|---|---|
| DFC D&A ≈ DVA `7.04.01` | D&A |
| Soma dos conceitos-filho ≤ total de saídas/entradas do pai `S` | dupla contagem |
| DFC `6.05` = Δ `1.01.01` do BPA (a Camada 6 já faz) | fechamento |
| DRE `3.11` ≈ distribuição do lucro na DVA | lucro |
| Dividendos pagos ≈ declarados − Δ dividendos a pagar (precisa da DMPL) | dividendos |

4. **Lacunas de dado que limitam a etapa:**
   - **DMPL não ingerida**: dividendos declarados, recompras e aumentos de capital;
   - **só o consolidado está carregado**: sem o individual da controladora, holdings ficam incompletas.

## Stress test

Script: [`stress/st7_taxonomia.py`](stress/st7_taxonomia.py). São 1.755 DFPs do plano padrão, com 80.009
linhas N da DFC.

**(a–c) Cobertura, dupla contagem e sinal, por conceito:**

| Conceito | Cobertura | Linhas | Em 2+ conceitos | Sinal trocado |
|---|---|---|---|---|
| D&A | 98,5% | 2.090 | 0 | 0,4% |
| D&A de direito de uso | 7,2% | 129 | 0 | 0,8% |
| Capex imobilizado | 88,7% | 1.615 | 36 | 0,8% |
| Capex intangível | 52,8% | 941 | 36 | 0,7% |
| Dividendos/JCP pagos | 91,2% | 1.921 | 0 | 0,4% |
| **Juros pagos** | 86,6% | 2.336 | 0 | **16,6%** |
| Captação de dívida | 64,2% | 1.573 | 72 | 5,3% |
| Amortização de dívida | 72,5% | 1.748 | 60 | 2,5% |
| Arrendamento pago | 46,7% | 1.033 | 12 | 3,4% |
| Recompra | 58,1% | 1.152 | 0 | 7,7% |
| IR/CS pagos | 78,4% | 1.481 | 0 | 3,1% |

- **Juros pagos com 16,6% de sinal trocado**: a regra pega juros **provisionados** somados de volta em
  `6.01.01` (não é caixa). A regra tem de ficar restrita a `6.01.02`, `6.01.03` e `6.03` e excluir
  "provisionados", "apropriados" e "incorridos".
- **108 linhas caem em dois conceitos.** A maior parte é "Empréstimos: captação e amortização" (60), numa
  linha só com o valor líquido, e "Aquisição de imobilizado e intangível" (36). As duas precisam de
  conceitos próprios (`divida_liquida_fluxo`, `capex_total`), não de desempate.
- A cobertura do capex intangível caiu para 52,8% (79,7% num teste anterior) porque as linhas conjuntas
  saíram do intangível para evitar dupla contagem. Isso confirma o conceito `capex_total`.

**(d) Capex maior que o total de saídas de `6.02`**: 0,00% dos filings. Não há dupla contagem material.

**(e) Gabarito externo: D&A da DFC × DVA 7.04.01** (n = 1.748):

| Faixa | Filings |
|---|---|
| a menos de 2% | **82,2%** |
| a menos de 10% | 88,2% |
| DFC > 110% da DVA | 129 |
| DFC 102–110% | 66 |
| DFC < 90% | 56 |
| DFC 90–98% | 39 |
| DFC sem D&A | 21 |

Nos filings abaixo de 90%, as linhas que a regra deixou de fora incluem "amortização de mais-valia" e
"amortização de direito de concessão/ágio". São D&A para a DVA, e a regra as exclui de propósito (mais-valia
e ágio). A escolha é de definição, não de detecção: o conceito precisa dizer se inclui PPA (amortização de
mais-valia de aquisição) ou não. Acima de 110%, a DFC inclui itens que a DVA não conta como retenção (por
exemplo, a amortização de ativos de contrato). A proposta é criar dois conceitos, `da_ex_ppa` e `da_total`,
e usar a DVA como gabarito do `da_total`.

**(f) Modelo em empresas nunca vistas** (GroupKFold = 5, por empresa):
- F1 macro contra as regras de **0,918**, e concordância geral de 96,8%;
- 2.589 discordâncias (3,2%), das quais 778 com confiança ≥ 0,9.

As discordâncias apontam erros nos dois sentidos:

| Tipo | Exemplos (confiança do modelo) |
|---|---|
| **Regra faltante** (o modelo acerta) | "financiamentos e debêntures captação" → capt_divida (1,00); "ações de tesouraria" → recompra (1,00); "direito de uso amortizado" → D&A direito de uso (1,00); "no imobilizado" (sob 6.02) → capex (1,00) |
| **Falso positivo da regra** (o modelo acerta) | "caixa recebido na operação de sale and leaseback" ≠ arrendamento pago; "impostos a recolher e provisão IR e CS" (variação de capital de giro) ≠ IR pago; "exaustão de ativos biológicos" (debatível) |
| **Erro do modelo** (herdado da regra) | "[6.01.01.04] juros" → juros_pagos: é provisão, e o modelo aprendeu o erro da regra de juros |

**(g) Estabilidade da série**: um conceito presente em Y−1 e Y+1 mas ausente em Y aparece em 28 de 10.403
casos (0,3%). Isso confirma que agregar por conceito resolve a fragmentação que a Etapa 6 mediu na DFC.

**Veredito: viável, com três correções antes de publicar:**
1. Corrigir a regra de juros pagos pelo pai (só fluxo de caixa, não o ajuste de `6.01.01`).
2. Criar os conceitos `capex_total`, `divida_liquida_fluxo`, `da_total` e `da_ex_ppa`.
3. Excluir "sale and leaseback" (é entrada) e "a recolher/provisão" (é capital de giro) das regras.

O ciclo regra → modelo → discordância funciona como pretendido: cada rodada revela a próxima correção.
Mas o modelo **herda os erros das regras**, então a checagem pelas identidades (e) e o sinal (c) são
obrigatórios antes de publicar, não opcionais.

## Critério de pronto (por conceito)

- Cobertura ≥ 85% dos DFPs em que o conceito se aplica.
- Sinal trocado < 1%.
- Nenhuma linha em dois conceitos.
- Identidade externa (quando existe) passando em ≥ 90% a menos de 2%.
- Precisão ≥ 98% numa amostra de 100 linhas estratificada por empresa, revisada à mão.

## Resultado (2026-10-16)

**Entrou** (`scripts/analysis/taxonomia.py`, migração `2026-10-16_taxonomia.sql`, 8 testes em `tests/test_taxonomia.py`):
- **Conceitos** (`conceito`): 16 da DFC (D&A em três partes e `da_total`; capex imobilizado, intangível, conjunto e
  `capex_total`; dividendos, juros, captação, amortização, dívida líquida em linha única, arrendamento, recompra, IR) e 11
  de contas fixas (`receita_liquida`, `ebit`, `lucro_liquido`, `cfo`/`cfi`/`cff`, `caixa_final`, `ativo_total`…).
- **Regras com as três correções do stress test**: juros pagos só em `6.01.02`, `6.01.03` e `6.03`, sem provisionados,
  apropriados nem salários; conceitos `capex_total`, `divida_liquida_fluxo`, `da_total` e `da_ex_ppa`; "sale and
  leaseback" e "a recolher/provisão" fora. Só linhas folha entram (um pai e seus filhos não se somam duas vezes).
- **Voto por linha econômica (Etapa 6)**: o conceito majoritário da linha vale para todos os filings dela, mas só se
  ao menos metade deles foi classificada pela regra (senão a Etapa 6 provavelmente ligou duas contas diferentes).
- **`fato_padronizado`**: 138 mil fatos de 140 empresas, com `metodo`, `confianca`, `checagem` e `publicado`. A D&A é
  conferida com a DVA 7.04.01 e aceita a definição alternativa da empresa (sem direito de uso, sem mais-valia).
  Capex maior que as saídas de `6.02` e sinal trocado reprovam o fato.
- **`get_financials`** no MCP (item 3.4 da Etapa 3), que devolve o fato com `metodo` e `checagem` (a regra 12 do
  `CLAUDE.md` não se perde). Sexta ferramenta; passa do teto de cinco do doc da Etapa 3, a medir na avaliação.

**Cobertura** (DFPs do plano padrão com DFC; "onde se aplica" não é conhecido, então 100% não é a meta de todos):

| Conceito | DFPs | Cobertura | | Conceito | DFPs | Cobertura |
|---|---|---|---|---|---|---|
| da_total | 1.730 | 98,6% | | juros_pagos | 1.408 | 80,2% |
| dividendos_pagos | 1.599 | 91,1% | | ir_pago | 1.352 | 77,0% |
| capex_total | 1.534 | 87,4% | | amort_divida | 1.245 | 70,9% |
| capt_divida | 1.052 | 59,9% | | recompra | 955 | 54,4% |
| arrend_pago | 776 | 44,2% | | divida_liquida_fluxo | 46 | 2,6% |

**Critérios de pronto, por conceito:**

| Critério | Resultado |
|---|---|
| Cobertura ≥ 85% | **da_total, dividendos, capex_total**; os demais dependem de a empresa ter a linha (arrendamento, recompra, captação), sem denominador de "aplicável" |
| Sinal trocado < 1% | **0% por construção**: linha de sinal contrário ao esperado sai do conceito (venda de tesouraria não é recompra). O custo é cobertura menor |
| Nenhuma linha em dois conceitos | **Cumprido**: conflito vira "sem conceito" e a regra específica vence a geral |
| Identidade D&A × DVA ≥ 90% a menos de 2% | **Não atingido**: 1.468 `ok` + 77 `ok_*` de 1.730 = **89,5%** com a definição alternativa (**84,9%** só com a total). A DVA 7.04.01 não tem definição única entre empresas |
| Precisão ≥ 98% em amostra de 100 linhas | **Atingido em 2026-10-30 por revisão exaustiva (não amostra)**, ver abaixo; antes: duas rodadas de revisão **minha** (não de um analista), 97 e 140 linhas, deram ~92% e ~88% **antes** das últimas correções. Os piores: `divida_liquida_fluxo` (nome ambíguo, 3 a 7 em 10 errados), e rótulos propagados pelo voto para linhas de nome diferente. Não revisei a amostra final |

### Revisão exaustiva dos três piores conceitos (2026-10-30)

[`stress/st7_revisao.py`](stress/st7_revisao.py) lista **todos** os nomes de linha que entram em fatos de um conceito
(célula a célula, depois do voto e da checagem de sinal), sem amostra; `ERROS` guarda a revisão nome a nome. Revisão
feita por Claude, não por analista: os nomes e o motivo de cada erro estão no script, para conferir.

| Conceito | Células | Erros antes | Precisão antes | Depois |
|---|---|---|---|---|
| `divida_liquida_fluxo` | 181 | 130 (mútuo com ligadas/coligadas; "emissão de debêntures líquida de gastos" é captação) | **28,2%** | 51 células, 0 erros |
| `recompra` | 3.573 | 158 (exercício de opções e ILP com tesouraria, venda/alienação, "recompra de cessão de recebíveis", ações de investidas/controladas) | 95,6% | 3.415, 0 erros |
| `arrend_pago` | 3.789 | 106 (linhas que misturam dívida e arrendamento, adição/constituição/ganho/baixa não caixa, pré-pagamento) | 97,2% | 3.691, 0 erros |

A maior parte dos erros de `recompra` não vinha da regra, mas do **voto da linha econômica**: a Etapa 6 liga "Ações em
tesouraria" e "Alienação de ações em tesouraria" na mesma linha, e o conceito majoritário era propagado para o nome que a
própria regra exclui. Agora a propagação não vence a exclusão; a célula fica com o conceito que a regra dá ao próprio nome
(ou nenhum). A mudança vale para todos os conceitos, comparada fato a fato contra a base anterior:

- `capex_total` +18 fatos, nenhum perdido: linhas líquidas ("Adições/Baixas no Imobilizado e Intangível", "Baixa (Aquisição)
  de bens", "(Compra) venda de intangível") passam a ser aceitas explicitamente, com o sinal decidindo; antes entravam só
  por acidente da propagação.
- `capt_divida` +54: "captações… líquidas dos gastos" saiu da dívida líquida e foi para captação.
- `amort_divida` −72, `juros_pagos` −10, `ir_pago` −6: nomes que a regra já excluía (principal **e** juros na mesma linha,
  dívida **e** arrendamento, IR a pagar/diferido/provisão) e que a propagação furava. Coerente com a definição; custa
  cobertura em empresas que só publicam a linha mista.
- D&A sem mudança relevante (`da_total` +3).

**Segunda rodada, os demais conceitos (mesmo dia).** Todos os nomes dos outros 11 conceitos de regra (~1.600 nomes)
revistos da mesma forma:

| Conceito | Células | Precisão antes | Erros principais |
|---|---|---|---|
| `amort_divida` | 6.386 | 91,5% | derivativos ("financ" casava "instrumentos financeiros"), custo/comissão de estruturação, parcelamento de tributos, "direitos de uso"/"leasing" |
| `da_ppa` | 705 | 91,9% | "provisão para perdas/amortização de ágio", custo de captação junto com ágio, AVP de arrendamento |
| `juros_pagos` | 6.957 | 96,3% | principal e juros na mesma linha, "arredamento"/leasing/IFRS 16, RGR, nomes sem juros vindos do voto |
| `da_ex_ppa` | 7.707 | 97,1% | amortização de custo de captação, direito de uso escrito de outro jeito, impairment, itens não D&A |
| `capt_divida` | 5.001 | 98,5% | devolução de empréstimo concedido, custo da emissão, linha mista com arrendamento |
| `ir_pago` | 5.532 | 99,3% | IRRF sobre JCP, "refin" de impostos |
| demais (dividendos, capex, `da_direito_uso`) | — | 99,1–99,9% | não caixa, M&A (ágio), erros de digitação que escapavam da exclusão |

Depois: **0 erros** em todos os 14 conceitos, nos nomes revistos. Mudanças além das regras:
- **o nome vence o voto**: quando a regra dá ao próprio nome um conceito (igual ou outro), vale esse; o voto só rotula o que
  a regra não reconhece. "Pagamento de empréstimos" ligado a uma linha de juros continua amortização.
- a isenção de linha líquida de capex neutraliza só as palavras de baixa/venda (antes passava por cima de toda a exclusão);
- `divida_liquida_fluxo` reconhece "emissão/pagamento de debêntures" e "ingressos/amortizações" (51 → 75 células).

Efeito na identidade D&A × DVA (DFPs): **89,5% → 90,4%** com as definições alternativas (o critério de 90% passa a ser
cumprido) e 84,9% → 86,0% só com a total. `da_total` perde 35 fatos de empresas que só publicam "depreciação, amortização e
impairment" ou "outros ajustes (depreciação/tributos retidos)": perda de cobertura deliberada. `amort_divida` cai mais
(4.927 → 4.770 fatos nas duas rodadas): linhas mistas de principal e juros ou de dívida e arrendamento ficam sem conceito.

Limites: revisão do Claude, nome a nome, não de analista (a lista `ERROS` está no script para conferir); precisão contra a
leitura do nome, não contra o valor na nota explicativa. Nome novo que aparecer numa carga futura não está revisto: rode
`st7_revisao.py <conceito> --listar` depois de cada mudança de regra.

**Não implementado**, de propósito:
- **Modelo supervisionado e fila de revisão humana (3.b e 3.c)**: o modelo herda os erros das regras (o stress test
  mostrou) e exige scikit-learn na venv; a revisão humana é de um analista. As discordâncias regra × modelo seguem
  disponíveis em `stress/st7_taxonomia.py`.
- **DMPL** (dividendos declarados, recompras) e **demonstrações individuais**: não ingeridos.
- **Bancos e seguradoras**: sem conceitos (plano diferente).
- **Safra reapresentada**: só a coluna `Último` de cada filing; ITR entra como acumulado do ano.

**Veredito: implementada e publicável com ressalvas.** Os fatos de `da_total`, `capex_total` e `dividendos_pagos` passam em
cobertura, sinal e, no caso da D&A, na identidade com a DVA a ~85–90%. **A precisão de 98% não foi demonstrada**: antes de
um analista usar `divida_liquida_fluxo`, `arrend_pago` ou `recompra` sem olhar a linha, falta a revisão estratificada que
este doc pediu. O `get_financials` expõe `metodo` e `checagem` justamente para isso.

### Avaliação da Etapa 2 com as seis ferramentas (2026-10-15)

`avaliacao/runs/2026-10-15_etapa7.json`: 27/28 certas (96,4%), zero erros de ferramenta, zero consultas abortadas,
4,4 chamadas e ~319 mil tokens por pergunta (a execução da Etapa 4 tinha 100%, 4,3 e ~302 mil). Montado de duas rodadas:
20 perguntas de 2026-10-13 e 8 refeitas em 2026-10-15, porque a primeira caiu no limite de uso da conta.

- **O único erro é a q027** (BLAU3, lucro líquido 2024): o modelo investigou o PDF, concluiu que a "reapresentação" do DFP
  2025 é um erro de sinal na própria fonte e respondeu original = reapresentado = R$ 213,5 mi. O gabarito pede os dois
  valores publicados lado a lado (R$ 213,5 mi e R$ 245,9 mi). A análise dele é defensável, mas contraria a regra 3 da
  skill ("nunca troque um pelo outro em silêncio"); fica como erro.
- **Esta avaliação não exercita o `get_financials`**: o v0 não tem pergunta de DFC por conceito (D&A entra pela DVA, via
  `query`), então o efeito da ferramenta em acerto e tokens **não foi medido**. A v1 (~80 perguntas, com "capex de X em
  2023" e "dividendos pagos") é o que falta para isso. A diferença de +5% de tokens para a Etapa 4 está dentro do ruído de
  uma execução (sessões diferentes, prefixo de contexto igual).
