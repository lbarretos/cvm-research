# Etapa 6: Taxonomia canônica entre empresas (camada L2)

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
   balanço resumido (vêm direto de contas `S` pelo `plano_cvm` da Etapa 4) mais os 11 da DFC testados abaixo.
2. **Classificação das contas N em três passos:**
   - (a) **regras** (regex sobre o nome normalizado + prefixo do pai + exclusões + sinal esperado);
   - (b) **modelo supervisionado** (TF-IDF de n-gramas de caracteres + pai + sinal, regressão logística)
     treinado nos rótulos das regras;
   - (c) **revisão humana** das discordâncias entre (a) e (b), com prioridade para confiança alta e
     materialidade alta.

   A decisão é gravada por **linha econômica** (Etapa 5), não por filing.
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

Script: [`stress/st5_taxonomia.py`](stress/st5_taxonomia.py). São 1.755 DFPs do plano padrão, com 80.009
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
casos (0,3%). Isso confirma que agregar por conceito resolve a fragmentação que a Etapa 5 mediu na DFC.

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
