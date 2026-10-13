# Etapa 5: Versões do template da CVM (camada L0 dos demonstrativos)

## Avaliação atual

O código fixo da CVM (`st_conta_fixa = 'S'`) é tratado como estável: o mesmo código seria sempre a
mesma conta. Dentro de uma versão do plano de contas isso vale. No plano padrão, o nome mais comum de
cada código `S` cobre 100% das linhas em DRE, DFC e DVA e 99,1% no BPP. **No BPA cobre só 87,9%**, e o
motivo não é variação de redação.

Na adoção do IFRS 9, a CVM inseriu contas de aplicação financeira em `1.01.02` e `1.02.01` e **deslocou
os códigos seguintes em uma posição**:

| Código | Template antigo (até 2019-09) | Template novo (desde 2018-03) |
|---|---|---|
| 1.02.01.03 | Contas a receber | Aplicações ao custo amortizado |
| 1.02.01.04 | Estoques | Contas a receber |
| 1.02.01.05 | Ativos biológicos | Estoques |
| 1.02.01.06 | Tributos diferidos | Ativos biológicos |
| 1.02.01.07 | Despesas antecipadas | Tributos diferidos |
| 1.02.01.08 | Créditos c/ partes relacionadas | Despesas antecipadas |
| 1.02.01.09 | Outros ativos não circulantes | Créditos c/ partes relacionadas |
| 1.02.01.10 | — | Outros ativos não circulantes |

São 18 códigos `S` com mais de um significado no plano padrão, 59 no dos bancos e 35 no das seguradoras.

Onde isso pesa:
- **Camada 5.** Ela usa `codigo_fixo_confiavel=True` e trata essas trocas como `estavel`, sem gravar nada.
- **Camadas 2 e 3.** Geram falsos positivos no período de 31/12/2017, quando o DFP 2017 (layout antigo) é
  comparado com a coluna Penúltimo dos ITRs de 2018 (layout novo). No BPA houve 2.046 `reclassificacao`
  contra ~250 num ano típico, e 1.411 `divergencia_nao_explicada` em `1.01.02`/`1.02.01` contra ~30.
- **Consultas.** Qualquer série por `cd_conta` do ativo não circulante cruza a quebra e mistura contas
  diferentes. As views atuais não são afetadas: `1`, `1.01`, `1.01.01`, `2.01.04`, `2.02.01` e `2.03` não
  mudaram.
- A Camada 6 e o visualizador **não são afetados**, porque casam com `codigo_fixo_confiavel=False`.

## Proposta

| # | Ação |
|---|---|
| 5.1 | Tabela `plano_cvm(plano, tipo_doc, versao_template, cd_conta, ds_conta_norm, conceito_id)`, com uma linha por conta `S` de cada versão |
| 5.2 | `filings.versao_template` (a coluna nova da Etapa 1), detectada **filing a filing** pela impressão digital das contas `S` e nunca pela data |
| 5.3 | Crosswalk `plano_cvm_de_para(versao_a, cd_a, versao_b, cd_b)`, escrito à mão (são 18 códigos no plano padrão) |
| 5.4 | Camada 5: considerar o código `S` confiável **só quando a `versao_template` dos dois filings é a mesma**; entre versões, usar o crosswalk |
| 5.5 | Camadas 2 e 3: comparar pares de versões diferentes pelo crosswalk, não pelo código literal. Depois, rodar de novo as Camadas 2, 3 e 5 com `--full` |

## Stress test

Script: [`stress/st5_template_versao.py`](stress/st5_template_versao.py). Agrupa os filings por impressão
digital das contas `S`: dois filings ficam na mesma versão se nenhum código tem nome diferente entre eles.
Depois verifica monotonicidade, ambiguidade e o que a Camada 5 gravou.

**1) Quantas versões aparecem** (as de 1 a 2 filings são renomeações de uma empresa só):

| Plano | BPA | BPP | DRE | DFC | DVA |
|---|---|---|---|---|---|
| padrão | 2 (+3 isoladas) | 2 | **1** | 1 (+3 isoladas) | **1** |
| banco | 3 (+1) | 3 | **19** | 2 (+2) | 2 |
| seguradora | 3 | 2 | 2 | 3 (+2) | 2 |

**2) A hipótese "cada empresa migra uma vez e não volta" é falsa.**

| tipo_doc | Séries | Com troca | **Voltam ao template antigo** |
|---|---|---|---|
| BPA | 292 | 211 | **48** |
| BPP | 292 | 213 | 22 |
| DFC | 292 | 8 | 5 |
| DRE | 292 | 9 | 5 |
| DVA | 292 | 6 | 0 |

Verificação manual: 50 empresas migram no ITR de 2T18, **voltam ao layout antigo no ITR de 1T19** e
migram de novo no 2T ou 3T19. Exemplo: `00.864.214/0001-06`, com antigo até 1T18, novo em 2T18–3T18,
antigo em 1T19–2T19 e novo desde 3T19. Por isso **uma regra por data erraria**, e a detecção precisa ser
filing a filing (5.2).

**3) Ambiguidade**: filings compatíveis com mais de uma versão porque omitem justamente as contas que as
distinguem.

| Plano | Ambíguos |
|---|---|
| padrão | 1 de ~34 mil |
| seguradora | 0 |
| banco | BPA 33 de 150, **DRE 63 de 150** |

**4) A Camada 5 hoje**: de 5.593 casos de conta `S` com o mesmo código e nome diferente entre filings
consecutivos, **5.585 ficaram como `estavel`** (não gravados) e 8 como `nova`.

**Veredito: aprovada com ajustes.**
- No plano padrão e nas seguradoras, a impressão digital funciona: poucas versões, sem ambiguidade.
- A versão tem de ser detectada por filing (5.2). A data não serve (item 2).
- **Nos bancos, a impressão digital estrita falha** (19 "versões" de DRE e 42% dos filings ambíguos):
  os bancos renomeiam contas `S` à vontade. Para eles, a versão sai de poucas **contas-âncora** com voto
  da maioria (por exemplo, o nome de `3.01.02` e `1.02`, que marcam as re-letragens de 2017, 2018 e 2020).
  Como são 4 bancos, uma tabela manual por filing também é viável.

## Critério de pronto

- Todo filing com `versao_template` preenchida e nenhum ambíguo no plano padrão.
- Depois de rodar de novo, a contagem da Camada 2 no BPA em 2017 volta à faixa de ~250 `reclassificacao`, e
  a da Camada 3 à faixa de ~30 erros.
- Teste de regressão com a empresa `00.864.214/0001-06` (antigo, novo, antigo, novo).

## Resultado (2026-10-14)

**Entrou** (`scripts/ingest/template_versions.py`, ligado ao `rebuild_filings`, que roda no início de todo `run_all.py`):
- **5.1** `plano_cvm`: as contas S de cada (plano, tipo_doc, versão), pelo voto dos filings atribuídos sem ambiguidade.
- **5.2** `filings.versao_template` (`v1`, `v2`…), detectada filing a filing pela impressão digital. NULL quando o filing
  é compatível com mais de uma versão ou o plano tem versões demais para a regra ser confiável.
- **5.3** `plano_cvm_de_para`: derivada por (pai, nome) entre versões, não escrita à mão. Para o BPA padrão v1 → v2 ela
  reproduz a tabela deste documento (1.02.01.03 → .04 … .08 → .09, mais 1.02.01.02 → .03).
- **5.4** Camada 5: o código S só é confiável quando os dois filings são da mesma versão; entre versões, o par casa pelo
  nome (`renumerado`).
- **5.5** Camadas 2 e 3: `iter_pairs` traduz os códigos S do filing comparado para os do baseline pelo de-para (e leva os
  descendentes de uma conta deslocada junto). Camada 6 e visualizador não mudam.
Testes: `tests/test_template_versions.py` (4), com o cenário antigo → novo → antigo → novo.

**Feito na cópia do banco, não no banco vivo.** As Camadas 2, 3 e 5 foram recalculadas numa cópia (`--full`, sem erros) e
comparadas com as contagens de antes (arquivos `avaliacao/flags_camadas235_{antes,depois}_etapa5.txt`). O banco vivo recebe
a coluna e as versões no próximo `rebuild_filings` (job semanal ou `run_all.py`), e as camadas sozinhas passam a usá-las
na rodada seguinte.

**Versões detectadas (padrão):** BPA 5 (v1: 2.776 filings 2010–2019-09, 102 empresas; v2: 4.150 filings 2018-03 em
diante, 140 empresas; v3–v5 são 1 a 2 filings de uma empresa cada), BPP 2, DRE 1, DVA 1, DFC 4. A empresa
`00.864.214/0001-06` sai v1 (até 1T18), v2 (2T18–3T18), v1 (1T19–2T19), v2 (desde 3T19), como no stress test.

**Critérios de pronto:**

| Critério | Resultado |
|---|---|
| Todo filing com versão e nenhum ambíguo no plano padrão | **Quase**: 1 de 6.890 DFC_MI padrão sem versão. Fora do padrão: DRE de banco (150 de 150) e DFC de seguradora (69 de 69) ficam NULL por terem versões demais; BPA de banco 33 de 150 |
| BPA 2017: ~250 `reclassificacao` e ~30 erros da Camada 3 | **Não atingido**: `reclassificacao` 3.244 → 2.069 (−36%) e `divergencia_nao_explicada` 1.615 → 338 (−79%) |
| Teste de regressão da empresa antigo/novo/antigo/novo | Cumprido (sintético nos testes, real na cópia) |

Sobre o segundo critério: o "~250" do stress test não é a faixa de um ano típico. Os anos vizinhos têm 884 (2016) e 1.219
(2018) `reclassificacao` no BPA de 31/12. O que sobra em 2017 são v1 → v2 que **não são troca de template**: o mesmo
período comparado entre o DFP original e a coluna Penúltimo de ITRs de 2018, quando muitas empresas reapresentaram o
comparativo ao adotar IFRS 9/15 (flags `reapresentacao` e `reclassificacao` legítimas).

**Limitações conhecidas:**
- **Bancos**: DRE sem versão (a regra da impressão digital não vale; a proposta de contas-âncora ficou de fora).
- **Nome repetido na versão antiga**: `1.02.01.09` e `1.02.01.10` são ambas "Outros ativos não circulantes" em filings
  v1; o de-para não mapeia `.09` → `.10`. Uma regra por exclusão colidiu com filings que têm os dois códigos e piorou a
  Camada 3 (338 → 1.312), então foi revertida. É a maior parte do que resta de falso positivo em `1.02.01.09.*`.
- **Camada 5**: `renumerado` sobe de 849 para 1.162 e `ambiguo` de 10.562 para 10.879 (as trocas de template passam a
  ser gravadas em vez de ficarem como `estavel`; o acréscimo da fila `ambiguo` é de revisão humana).

**Veredito: implementada e funcional; o critério numérico da Camada 2/3 em 2017 não foi atingido (a meta estava
calibrada errado) e os bancos ficam fora.**
