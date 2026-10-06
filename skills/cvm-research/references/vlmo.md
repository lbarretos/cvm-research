# VLMO: insider trading (`vlmo_movimentacoes`)

Formulário mensal em que a companhia informa as posições e movimentações de controladores,
conselheiros, diretores, conselho fiscal e órgãos estatutários (e seus vinculados) com valores
mobiliários dela, da controladora e das controladas. Estruturado a partir de 2018.

## O que mudou em relação à versão antiga desta skill

A orientação antiga ("cada operação aparece ~6×, use `SELECT DISTINCT`", "a data exata não
existe, use ±45 dias") valia para o banco antigo no Supabase. No banco atual:

- o ingestor já remove as linhas repetidas do CSV da CVM (chave única `vlmo_mov_uniq`);
- a repetição que sobra vem de **versões**: quando a companhia reapresenta o formulário do mês, a
  CVM publica o documento inteiro de novo com `versao` maior, e as duas versões ficam no banco;
- `data_movimentacao` está preenchida em 100% das compras e vendas.

`SELECT DISTINCT` agora é o erro: funde duas operações legítimas com os mesmos valores e não
remove a versão antiga quando ela difere da nova.

Até 30/09/2026 as linhas de `Saldo Inicial` se repetiam a cada recarga (NULL em
`data_movimentacao` escapava do índice único); a origem da velha "duplicação ~6×" era essa. Foi
corrigido e limpo: a posição pode ser somada direto, na última versão.

## Limites do dado

- **Defasagem de ~1 mês.** O formulário do mês é entregue até o dia 10 do mês seguinte; em fins
  de setembro, o último mês completo costuma ser agosto. Diga até quando vai o dado.
- **Não identifica a pessoa.** O VLMO agrega por cargo (`Controlador ou Vinculado` etc.); não dá
  para dizer qual controlador, conselheiro ou veículo operou.
- **Versão nova pode chegar depois.** Um mês com só a v1 pode ser corrigido; a v2 do mesmo mês às
  vezes traz operações que a v1 omitia.
- **Preço com erro de digitação** existe (ex.: R$ 0,42 numa ação de R$ 42). Se o preço destoar
  muito do resto do mês, sinalize em vez de somar o volume.

## Colunas que importam

| Coluna | Uso |
|---|---|
| `data_referencia` | mês do formulário (sempre dia 1). Chave da versão, não a data da operação |
| `versao` | versão do formulário do mês; use a maior |
| `data_movimentacao` | data da operação. Use esta para períodos e triangulação |
| `tipo_cargo` | `Controlador ou Vinculado`, `Conselho de Administração ou Vinculado`, `Diretor ou Vinculado`, `Conselho Fiscal ou Vinculado`, `Órgão Estatutário ou Vinculado` |
| `tipo_empresa` / `empresa` | de quem é o papel: `Companhia` (a própria), `Controladora` ou `Controlada`. Para "insider comprando ação da empresa", filtre `tipo_empresa = 'Companhia'` |
| `tipo_ativo` / `caracteristica` | Ações, Debêntures, Opções… / ON, PN, UNT |
| `tipo_operacao` | `Crédito` (entrada) ou `Débito` (saída) |
| `quantidade`, `preco_unitario`, `volume` | volume em R$ |

## Tipos de movimentação

`Saldo Inicial` é ~85% da tabela: é posição, não operação. Tire sempre, a não ser que a
pergunta seja sobre posição.

- **Mercado (sinal de intenção):** `Compra à vista`, `Venda à vista`, `Compra à termo`,
  `Venda à termo`, `Compra`, `Venda`.
- **Remuneração (não é decisão de mercado):** `Ações de plano de remuneração`,
  `Units de plano de remuneração`, `Ações decorrentes de exercício de opção de compra`,
  `Exercício de opção de Plano de Remuneração`, `Recebimento de opção de Plano de Remuneração`.
- **Aluguel de ações:** `Contratação/Devolução de empréstimo (locador|tomador)`. Volume alto e
  sem significado de convicção; não some com compra/venda.
- **Eventos societários:** `Desdobramento/bonificação`, `Grupamento`, `Subscrição`,
  `Homologação de subscrição`, conversões de debêntures.
- **Entrada/saída do cargo:** `Posse`, `Desligamento/saída` (a posição passa a contar ou deixa
  de contar; não é compra nem venda).
- **Outros:** `Doação`, `Herança`, `Permuta`, `Outras Entradas`, `Outras Saídas`. Em grupos
  familiares, `Outras Entradas`/`Outras Saídas` no mesmo dia e quantidade costumam ser transferência
  entre veículos do próprio controlador (volume 0): não é venda nem compra.

Para ver a lista na instalação: `SELECT tipo_movimentacao, COUNT(*) FROM vlmo_movimentacoes GROUP BY 1 ORDER BY 2 DESC`.

## Queries

### Operações de mercado (última versão de cada formulário)

```sql
WITH ult AS (
    SELECT cnpj_companhia, data_referencia, MAX(versao) AS versao
    FROM vlmo_movimentacoes
    WHERE cnpj_companhia = '<CNPJ>'
    GROUP BY 1, 2
)
SELECT v.data_movimentacao, v.tipo_cargo, v.tipo_movimentacao,
       v.tipo_ativo, v.caracteristica, v.quantidade, v.preco_unitario, v.volume
FROM vlmo_movimentacoes v
JOIN ult USING (cnpj_companhia, data_referencia, versao)
WHERE v.tipo_empresa = 'Companhia'
  AND v.tipo_movimentacao IN ('Compra à vista','Venda à vista','Compra à termo',
                              'Venda à termo','Compra','Venda')
  AND v.data_movimentacao >= date('now','-1 year')
ORDER BY v.data_movimentacao DESC;
```

### Saldo líquido por mês e cargo

```sql
WITH ult AS (
    SELECT cnpj_companhia, data_referencia, MAX(versao) AS versao
    FROM vlmo_movimentacoes WHERE cnpj_companhia = '<CNPJ>' GROUP BY 1, 2
)
SELECT substr(v.data_movimentacao, 1, 7) AS mes, v.tipo_cargo,
       SUM(CASE WHEN v.tipo_movimentacao LIKE 'Compra%' THEN v.quantidade ELSE 0 END) AS qtd_compra,
       SUM(CASE WHEN v.tipo_movimentacao LIKE 'Venda%'  THEN v.quantidade ELSE 0 END) AS qtd_venda,
       SUM(CASE WHEN v.tipo_movimentacao LIKE 'Compra%' THEN v.volume ELSE -v.volume END) AS volume_liquido,
       COUNT(*) AS operacoes
FROM vlmo_movimentacoes v
JOIN ult USING (cnpj_companhia, data_referencia, versao)
WHERE v.tipo_empresa = 'Companhia'
  AND v.tipo_movimentacao IN ('Compra à vista','Venda à vista','Compra à termo',
                              'Venda à termo','Compra','Venda')
  AND v.data_movimentacao >= date('now','-2 years')
GROUP BY 1, 2 ORDER BY 1 DESC, 2;
```

Some quantidade só dentro da mesma `caracteristica` (ON e PN têm preços diferentes); em volume
(R$) pode somar.

### Triangulação: fato relevante × insider (±7 dias)

```sql
WITH ult AS (
    SELECT cnpj_companhia, data_referencia, MAX(versao) AS versao
    FROM vlmo_movimentacoes WHERE cnpj_companhia = '<CNPJ>' GROUP BY 1, 2
), ops AS (
    SELECT v.* FROM vlmo_movimentacoes v JOIN ult USING (cnpj_companhia, data_referencia, versao)
    WHERE v.tipo_empresa = 'Companhia'
      AND v.tipo_movimentacao IN ('Compra à vista','Venda à vista','Compra à termo',
                                  'Venda à termo','Compra','Venda')
)
SELECT i.data_entrega AS data_fato, i.assunto,
       o.data_movimentacao,
       julianday(o.data_movimentacao) - julianday(i.data_entrega) AS dias_do_fato,
       o.tipo_cargo, o.tipo_movimentacao, o.quantidade, o.volume
FROM ipe_docs i
JOIN ops o ON o.cnpj_companhia = i.cnpj_companhia
          AND o.data_movimentacao BETWEEN date(i.data_entrega,'-7 days') AND date(i.data_entrega,'+7 days')
WHERE i.cnpj_companhia = '<CNPJ>'
  AND i.categoria = 'Fato Relevante'
  AND i.data_entrega >= date('now','-2 years')
ORDER BY i.data_entrega DESC, o.data_movimentacao;
```

`dias_do_fato` negativo (operação antes do fato público) é o que merece destaque. Não afirme
irregularidade: o dado mostra coincidência de datas, não conhecimento prévio. Compras de
controlador durante um programa de recompra também valem citar.

## Outras fontes relacionadas

- `vlmo_posicao`: um registro por formulário (protocolo, link). Use o `link_download` para
  mandar o usuário ao PDF original.
- `ipe_docs` com `categoria = 'Valores Mobiliários negociados e detidos (art. 11 da Instr. CVM nº 358)'`:
  o mesmo formulário em PDF, com texto extraído. Útil para 2015–2018, antes do dado estruturado.
