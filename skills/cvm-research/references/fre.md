# FRE: composição acionária e remuneração

O Formulário de Referência é reenviado várias vezes por ano. `data_referencia` é o **fim do
exercício do formulário** (o FRE 2026 vem com `2026-12-31`, uma data "futura"; em anos antigos a
convenção era `01-01`). A posição não tem data própria: `data_composicao_capital_social` está
vazia em toda a base. Um FRE novo pode repetir a posição do anterior sem atualizá-la; se os
percentuais forem idênticos aos do ano anterior, diga isso.

## Composição acionária

`fre_posicao_acionaria` traz a **cadeia de controle inteira**: os acionistas diretos da companhia
e, abaixo de cada holding, os sócios dela, com percentual **sobre a holding**. Somar ou ordenar a
tabela inteira dá pessoas com 100% ou 33% que não têm isso da companhia.

- Direto = `id_acionista_relacionado IS NULL`. Para descer na cadeia, `id_acionista_relacionado`
  aponta para o `id_acionista` da holding de cima.
- `vw_acionistas_diretos` já filtra o nível direto no FRE mais recente de cada empresa. Prefira.

```sql
-- Principais acionistas diretos
SELECT acionista, acionista_controlador, percentual_acao_ordinaria_circulacao AS pct_on,
       percentual_acao_preferencial_circulacao AS pct_pn, percentual_total_acoes_circulacao AS pct_total
FROM vw_acionistas_diretos WHERE cnpj_companhia = '<CNPJ>'
ORDER BY pct_total DESC LIMIT 15;

-- Bloco controlador, "Outros" e tesouraria (a soma do nível direto fecha ~100%)
SELECT data_referencia, versao,
       ROUND(SUM(CASE WHEN acionista_controlador = 'S' THEN percentual_total_acoes_circulacao END), 2) AS bloco_controlador,
       ROUND(SUM(CASE WHEN acionista LIKE 'Outros%' THEN percentual_total_acoes_circulacao END), 2) AS outros,
       ROUND(SUM(CASE WHEN acionista LIKE '%esouraria%' THEN percentual_total_acoes_circulacao END), 3) AS tesouraria,
       ROUND(SUM(percentual_total_acoes_circulacao), 2) AS soma
FROM vw_acionistas_diretos WHERE cnpj_companhia = '<CNPJ>' GROUP BY 1, 2;
```

**Free float** não vem pronto. Dê as duas leituras e diga qual é qual: a linha `Outros` (acionistas
abaixo do limite de divulgação) e `100 − bloco controlador − tesouraria` (que inclui veículos
familiares marcados como não controladores e investidores relevantes divulgados). Para empresa com
ON e PN, calcule por classe: o free float das PN costuma ser muito maior.

Para ver quem está atrás de uma holding controladora, desça um nível:
`WHERE id_acionista_relacionado = <id_acionista da holding>` no mesmo documento
(`data_referencia` e `versao`), lembrando que o percentual é sobre a holding.

## Remuneração dos administradores (`fre_remuneracao_orgao`)

Só tem o item 8.15 do FRE: **maior, menor e média da remuneração individual** e o número de
membros, por órgão (Conselho de Administração, Diretoria Estatutária, Conselho Fiscal). **Não tem a
remuneração global** proposta ou aprovada em assembleia; essa está na `Proposta da Administração` e
na `Ata` da AGO (`ipe_docs`, `especie`), ou na nota de partes relacionadas das DFs.

Armadilhas:
- **Cada FRE traz até três exercícios** (o corrente, previsto, e os dois anteriores),
  distinguidos por `data_fim_exercicio`. Filtre pelo exercício que interessa, não só pelo FRE.
- **Unidade misturada.** A companhia preenche em R$ ou em R$ mil, e a base guarda como veio. No
  mesmo FRE da Alpargatas, a média da diretoria aparece como 5.956,8 (R$ mil) num exercício e
  2.434.900 (R$) em outro. Antes de comparar anos, confira a ordem de grandeza: remuneração média
  anual de diretor estatutário abaixo de R$ 100 mil quase certamente está em R$ mil.
- O mesmo exercício muda entre FREs (reapresentação). Use o FRE mais recente que contém o
  exercício e diga se o valor mudou.

```sql
SELECT data_referencia AS fre, versao, data_fim_exercicio AS exercicio, orgao_administracao,
       numero_membros, valor_maior_remuneracao, valor_medio_remuneracao, valor_menor_remuneracao
FROM fre_remuneracao_orgao
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY data_fim_exercicio DESC, data_referencia DESC, versao DESC;
```
