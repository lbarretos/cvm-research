# CVM Research Database

Base de dados de documentos e eventos de empresas abertas brasileiras (CVM/B3).
Cobertura: 56 empresas da watchlist, fontes IPE + VLMO + Recompra + FRE.

## Como identificar uma empresa

Sempre use CNPJ como chave. Para buscar pelo ticker ou nome:
```sql
-- Por ticker
SELECT cnpj, nome_cvm FROM companies WHERE ticker = 'WEGE3';

-- Por nome parcial
SELECT cnpj, ticker, nome_cvm FROM companies WHERE nome_cvm ILIKE '%fleury%';
```

## Tabelas e campos principais

### `companies` — watchlist de empresas cobertas
`cnpj (PK), ticker, codigo_cvm, nome_cvm, setor, status_cvm`

### `ipe_docs` — catálogo de documentos corporativos
`protocolo_entrega (PK), cnpj_companhia, data_referencia, data_entrega,`
`categoria, tipo, especie, assunto, link_download,`
`texto_extraido (NULL = não extraído), extracao_falhou, chars_extraidos`

**Categorias relevantes:**
- `'Fato Relevante'` — eventos materiais (M&A, guidance, regulatório)
- `'Assembleia'` — AGO e AGE; `tipo` = `'AGO'` ou `'AGE'`
- `'Comunicado ao Mercado'` — comunicados gerais
- `'Resultado'` — release de resultados trimestrais
- `'Aviso aos Acionistas'`

### `vlmo_movimentacoes` — movimentações de valores mobiliários por insiders
`cnpj_companhia, data_referencia, tipo_cargo, tipo_movimentacao,`
`tipo_ativo, caracteristica (ON/PN), quantidade, preco_unitario, volume`

**tipo_cargo relevantes:** `'Conselho de Administração ou Vinculado'`, `'Diretoria ou Vinculado'`, `'Controlador ou Vinculado'`
**tipo_movimentacao:** `'Compra'`, `'Venda'`, `'Saldo Inicial'`, `'Saldo Final'`

### `recompra_programas` — programas de recompra de ações
`id_programa (PK), cnpj_companhia, finalidade_compra, data_deliberacao,`
`motivo, data_final_prazo, situacao ('Vigente'/'Encerrado')`

### `fre_capital` — composição do capital social (histórico)
`cnpj_companhia, data_referencia_doc, tipo_acao (ON/PN/Units), quantidade`

### `fre_remuneracao` — remuneração dos administradores
`cnpj_companhia, data_referencia_doc, orgao, num_membros,`
`remuneracao_fixa, remuneracao_variavel, total_remuneracao`

### `fre_composicao_acionaria` — principais acionistas
`cnpj_companhia, data_referencia_doc, nome_acionista, pct_on, pct_pn, pct_total`

### `fre_dividendos` — histórico de dividendos e JCP
`cnpj_companhia, data_referencia_doc, tipo_evento, tipo_acao,`
`data_aprovacao, data_pagamento, valor_por_acao`

### `fre_endividamento` — dívida estruturada
`cnpj_companhia, data_referencia_doc, tipo_divida, moeda, valor,`
`taxa_juros, data_vencimento`

---

## Queries de pesquisa padrão

### Histórico de assembleias (AGO + AGE) de uma empresa
```sql
SELECT data_referencia, tipo, especie, assunto,
       texto_extraido IS NOT NULL AS tem_conteudo,
       link_download
FROM ipe_docs
WHERE cnpj_companhia = '<CNPJ>'
  AND categoria = 'Assembleia'
ORDER BY data_referencia DESC
LIMIT 20;
```

### Fatos relevantes do último ano
```sql
SELECT data_referencia, assunto,
       LEFT(texto_extraido, 500) AS preview,
       link_download
FROM ipe_docs
WHERE cnpj_companhia = '<CNPJ>'
  AND categoria = 'Fato Relevante'
  AND data_referencia >= CURRENT_DATE - INTERVAL '1 year'
ORDER BY data_referencia DESC;
```

### Todos os documentos recentes (qualquer categoria)
```sql
SELECT data_entrega, categoria, tipo, assunto,
       texto_extraido IS NOT NULL AS tem_conteudo
FROM ipe_docs
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY data_entrega DESC
LIMIT 30;
```

### Movimentações de insiders (compras e vendas)
```sql
SELECT data_referencia, tipo_cargo, tipo_movimentacao,
       tipo_ativo, caracteristica, quantidade, volume
FROM vlmo_movimentacoes
WHERE cnpj_companhia = '<CNPJ>'
  AND tipo_movimentacao IN ('Compra', 'Venda')
ORDER BY data_referencia DESC
LIMIT 30;
```

### Triangulação: fato relevante + insider trading na mesma semana
```sql
SELECT
    i.data_referencia   AS data_fato,
    i.assunto           AS fato,
    v.tipo_cargo,
    v.tipo_movimentacao,
    v.volume
FROM ipe_docs i
JOIN vlmo_movimentacoes v
  ON i.cnpj_companhia = v.cnpj_companhia
 AND v.data_referencia BETWEEN i.data_referencia - 7 AND i.data_referencia + 7
WHERE i.cnpj_companhia = '<CNPJ>'
  AND i.categoria = 'Fato Relevante'
  AND v.tipo_movimentacao IN ('Compra', 'Venda')
ORDER BY i.data_referencia DESC;
```

### Programas de recompra vigentes
```sql
SELECT data_deliberacao, finalidade_compra, motivo,
       data_final_prazo, situacao,
       quantidade_acoes_ordinarias + COALESCE(quantidade_acoes_preferenciais, 0) AS total_acoes_programa
FROM recompra_programas
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY data_deliberacao DESC;
```

### Histórico de remuneração dos administradores
```sql
SELECT data_referencia_doc, orgao, num_membros,
       total_remuneracao,
       ROUND(total_remuneracao / NULLIF(num_membros, 0), 0) AS media_por_membro
FROM fre_remuneracao
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY data_referencia_doc DESC;
```

### Busca full-text no conteúdo de documentos
```sql
SELECT data_referencia, categoria, assunto,
       ts_rank(search_vector, query) AS relevancia,
       LEFT(texto_extraido, 300) AS trecho
FROM ipe_docs,
     to_tsquery('portuguese', 'aquisicao & controle') query
WHERE cnpj_companhia = '<CNPJ>'
  AND search_vector @@ query
ORDER BY relevancia DESC;
```

---

## Comportamento esperado ao pesquisar

1. **Sempre resolva o CNPJ primeiro** via `companies` antes de qualquer query.
2. **Verifique `texto_extraido`**: se `NULL`, exiba o `link_download` e informe que o conteúdo não foi extraído ainda.
3. **Para resumir assembleias**: leia `texto_extraido` e destaque deliberações sobre remuneração, mudanças estatutárias, eleição de conselho, aprovação de contas.
4. **Para fatos relevantes**: classifique o impacto — M&A, guidance, regulatório, operacional, financeiro.
5. **Para insider trading**: correlacione compras/vendas com fatos relevantes próximos e recompras vigentes.
6. **Documente documentos sem texto**: liste-os ao final com data + assunto + link, informando que precisam de extração manual se forem críticos.

## Monitorar uso do banco
```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS tamanho_db;
```
