# Receitas de SQL

Consultas prontas por tema, movidas do `CLAUDE.md` do projeto na Etapa 3. Use quando as ferramentas do MCP (`resolve_company`) não cobrirem; troque `<CNPJ>` pelo valor de `resolve_company`.

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
       substr(texto_extraido, 1, 500) AS preview,
       link_download
FROM ipe_docs
WHERE cnpj_companhia = '<CNPJ>'
  AND categoria = 'Fato Relevante'
  AND data_referencia >= date('now', '-1 year')
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
-- Só a última versao de cada (empresa, mês): uma versao nova é o reenvio completo do formulário
SELECT v.data_referencia, v.data_movimentacao, v.tipo_cargo, v.tipo_movimentacao,
       v.tipo_ativo, v.caracteristica, v.quantidade, v.preco_unitario, v.volume
FROM vlmo_movimentacoes v
WHERE v.cnpj_companhia = '<CNPJ>'
  AND v.versao = (SELECT MAX(versao) FROM vlmo_movimentacoes m
                  WHERE m.cnpj_companhia = v.cnpj_companhia
                    AND m.data_referencia = v.data_referencia)
  AND v.tipo_movimentacao IN (
      'Compra à vista', 'Compra à termo', 'Compra',
      'Venda à vista', 'Venda à termo', 'Venda'
  )
ORDER BY v.data_movimentacao DESC
LIMIT 30;
```

### Triangulação: fato relevante + insider trading na mesma semana
```sql
-- vlmo.data_referencia é sempre o dia 1 do mês: a janela usa data_movimentacao
-- (sem NULL em compras/vendas). Só a última versao do formulário mensal.
-- Uma linha por movimentação: fatos na mesma janela vão juntos em `fatos`, então SUM(volume) não dobra.
-- antes_do_fato = 1 se a operação precede ao menos um dos fatos (o caso que interessa para informação privilegiada).
SELECT
    v.data_movimentacao,
    v.tipo_cargo,
    v.tipo_movimentacao,
    ROUND(v.volume, 2)                                  AS volume,
    MAX(v.data_movimentacao < i.data_referencia)        AS antes_do_fato,
    COUNT(*)                                            AS n_fatos,
    GROUP_CONCAT(i.data_referencia || ' ' || i.assunto, ' | ') AS fatos
FROM vlmo_movimentacoes v
JOIN ipe_docs i
  ON i.cnpj_companhia = v.cnpj_companhia
 AND v.data_movimentacao BETWEEN date(i.data_referencia, '-7 days')
                             AND date(i.data_referencia, '+7 days')
WHERE v.cnpj_companhia = '<CNPJ>'
  AND i.categoria = 'Fato Relevante'
  AND v.versao = (SELECT MAX(versao) FROM vlmo_movimentacoes m
                  WHERE m.cnpj_companhia = v.cnpj_companhia
                    AND m.data_referencia = v.data_referencia)
  AND v.tipo_movimentacao IN ('Compra à vista', 'Compra à termo', 'Compra',
                             'Venda à vista', 'Venda à termo', 'Venda')
GROUP BY v.id
ORDER BY v.data_movimentacao DESC;
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
SELECT data_referencia, orgao_administracao, numero_membros,
       valor_medio_remuneracao,
       valor_maior_remuneracao,
       valor_menor_remuneracao
FROM fre_remuneracao_orgao
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY data_referencia DESC;
```

### Composição acionária (principais acionistas)
```sql
-- Acionistas diretos, FRE mais recente (a view já filtra nível, data e versão)
SELECT data_referencia, versao, acionista, acionista_controlador,
       percentual_acao_ordinaria_circulacao  AS pct_on,
       percentual_acao_preferencial_circulacao AS pct_pn,
       percentual_total_acoes_circulacao     AS pct_total
FROM vw_acionistas_diretos
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY percentual_total_acoes_circulacao DESC NULLS LAST
LIMIT 20;

-- Cadeia de controle: quem detém cada acionista direto (um nível acima; repita a junção para subir mais)
SELECT d.acionista AS acionista_direto, d.percentual_total_acoes_circulacao AS pct_na_companhia,
       c.acionista AS socio_do_acionista,  c.percentual_total_acoes_circulacao AS pct_no_acionista_direto
FROM vw_acionistas_diretos d
JOIN fre_posicao_acionaria c
  ON  c.cnpj_companhia  = d.cnpj_companhia
  AND c.data_referencia = d.data_referencia
  AND c.versao          = d.versao
  AND c.id_acionista_relacionado = d.id_acionista
WHERE d.cnpj_companhia = '<CNPJ>'
ORDER BY d.percentual_total_acoes_circulacao DESC, c.percentual_total_acoes_circulacao DESC;
```

### DRE trimestral (últimos 8 trimestres) via view
```sql
-- vw_dre = trimestre isolado; use vw_dre_acumulada para o acumulado no ano
SELECT fonte, data_referencia, dt_ini_exerc, dt_fim_exerc,
       receita_liquida, ebit, lucro_liquido,
       ROUND(ebit / NULLIF(receita_liquida, 0) * 100, 1) AS margem_ebit_pct
FROM vw_dre
WHERE cnpj_companhia = '<CNPJ>'
  AND fonte = 'ITR'
ORDER BY data_referencia DESC
LIMIT 8;
```

### DRE de banco ou seguradora
```sql
-- Confira o plano antes: vw_dre vem NULL para banco e seguradora
SELECT DISTINCT plano_contas FROM vw_plano_contas WHERE cnpj_companhia = '<CNPJ>';

SELECT fonte, data_referencia, dt_ini_exerc, dt_fim_exerc,
       receita_intermediacao, resultado_bruto_intermediacao, lair, ir_cs, lucro_liquido, lucro_controladora
FROM vw_dre_financeiro            -- vw_dre_seguradora para seguradoras (ebit, ebt, lucro_liquido …)
WHERE cnpj_companhia = '<CNPJ>' AND fonte = 'DFP'
ORDER BY data_referencia DESC
LIMIT 5;
```

### Balanço anual (DFP) — últimos 5 anos
```sql
SELECT data_referencia, dt_fim_exerc,
       ativo_total, caixa, ativo_circulante,
       divida_curto_prazo, divida_longo_prazo,
       divida_curto_prazo + COALESCE(divida_longo_prazo, 0) AS divida_total,
       patrimonio_liquido
FROM vw_balanco
WHERE cnpj_companhia = '<CNPJ>'
  AND fonte = 'DFP'
ORDER BY data_referencia DESC
LIMIT 5;
```

### DRE linha a linha (quando a view não tiver a conta que você quer)
```sql
SELECT data_referencia, cd_conta, ds_conta, vl_conta
FROM demonstrativos_contabeis
WHERE cnpj_companhia = '<CNPJ>'
  AND tipo_doc = 'DRE'
  AND fonte = 'DFP'
  AND ordem_exercicio = 'Último'
  AND versao = (
      SELECT MAX(versao) FROM demonstrativos_contabeis
      WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DRE' AND fonte = 'DFP'
        AND data_referencia = '<DATA>'
  )
ORDER BY cd_conta;
```

### Reapresentações e reclassificações de uma empresa (Camada 2)
```sql
-- Resumo por par de filings: quais períodos foram reapresentados e por quem
SELECT tipo_doc, periodo_ini, periodo_fim,
       fonte_ref || ' ' || data_ref AS baseline,
       fonte_cmp || ' ' || data_cmp || ' (' || ordem_cmp || ')' AS comparado,
       classificacao, severity,
       json_extract(detalhe, '$.linhas_divergentes') AS linhas_divergentes,
       json_extract(detalhe, '$.linhas_exclusivas_cmp') AS linhas_novas
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 2 AND cd_conta IS NULL
ORDER BY periodo_fim DESC, data_cmp;

-- Linhas: o que mudou na DRE anual de <ANO> entre o DFP original e o DFP seguinte
SELECT cd_conta, ds_conta, valor_ref AS original, valor_cmp AS reapresentado,
       diff_abs, ROUND(diff_rel * 100, 2) AS diff_pct, classificacao
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 2 AND tipo_doc = 'DRE'
  AND periodo_fim = '<ANO>-12-31' AND fonte_cmp = 'DFP' AND cd_conta IS NOT NULL
ORDER BY cd_conta;
```
Se a empresa não tiver linhas em `consistency_flags`, a Camada 2 ainda não rodou para ela — informar o
comando `run_all.py --layer 2 --cnpj <CNPJ>`. Ausência de flags para um período com filings pareados
significa que os valores bateram dentro da tolerância.

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

### Série trimestral com 4T derivado (Camada 6)
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

-- Fluxo de caixa operacional trimestral (DFC só existe acumulada na CVM; aqui já vem desacumulada)
SELECT dt_fim_exerc, trimestre, vl_final, flag
FROM demonstrativos_trimestrais
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DFC_MI' AND cd_conta = '6.01' AND safra = 'original'
ORDER BY dt_fim_exerc DESC LIMIT 8;

-- Auditar uma linha criada pela empresa: qual conta do filing anterior foi subtraída
SELECT dt_fim_exerc, trimestre, cd_conta, ds_conta, cd_conta_b, casamento,
       ROUND(vl_final/1e6, 1) AS vl_mi, flag,
       fonte_a || ' ' || data_a AS filing_a, fonte_b || ' ' || data_b AS filing_b
FROM demonstrativos_trimestrais
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DFC_MI' AND safra = 'original'
  AND cd_conta LIKE '6.03.%'
ORDER BY dt_fim_exerc DESC, cd_conta LIMIT 30;

-- Fila de revisão: pares que o casamento não teve confiança para usar
SELECT tipo_doc, data_ref, cd_conta, ds_conta,
       json_extract(detalhe,'$.cd_conta_b') AS cd_b,
       json_extract(detalhe,'$.ds_conta_b') AS candidato,
       ROUND(json_extract(detalhe,'$.score'), 3) AS score
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 6 AND classificacao = 'par_ambiguo'
ORDER BY score DESC;
```
Para comparar com o que a empresa reapresentou depois, repita com `safra = 'reapresentado'` e mostre as duas colunas lado a lado.

```sql
-- Linhas com layout misturado no trimestre e o que a Camada 2 mostra para o subtraendo (filing B)
SELECT t.dt_fim_exerc, t.trimestre, t.cd_conta, t.ds_conta, ROUND(t.vl_final/1e6, 1) AS vl_mi,
       r.vl_final IS NOT NULL AS tem_reapresentado, ROUND(r.vl_final/1e6, 1) AS reapresentado_mi,
       t.fonte_a || ' ' || t.data_a AS filing_a, t.fonte_b || ' ' || t.data_b AS filing_b
FROM demonstrativos_trimestrais t
LEFT JOIN demonstrativos_trimestrais r
  ON r.cnpj_companhia = t.cnpj_companhia AND r.tipo_doc = t.tipo_doc AND r.exercicio_ini = t.exercicio_ini
 AND r.trimestre = t.trimestre AND r.cd_conta = t.cd_conta AND r.safra = 'reapresentado'
WHERE t.cnpj_companhia = '<CNPJ>' AND t.safra = 'original' AND t.flag = 'reclassificacao_entre_filings'
ORDER BY t.dt_fim_exerc DESC, t.tipo_doc, t.cd_conta;
```
Na safra original, a versão reapresentada do mesmo trimestre costuma ser a que está num layout só (Vale 4T24: 3.04.03 =
−11,2 bi e 3.04.04 = 0 no reapresentado); confira se ela também não tem a flag antes de usá-la.

### Busca full-text no conteúdo de documentos (SQLite FTS5)

```sql
-- Antes da primeira busca, reconstruir o índice FTS (executar uma vez após ingestão):
-- INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild');

SELECT i.data_referencia, i.categoria, i.assunto,
       f.rank AS relevancia,
       substr(i.texto_extraido, 1, 300) AS trecho
FROM ipe_docs_fts f
JOIN ipe_docs i ON i.protocolo_entrega = f.protocolo_entrega
WHERE f.cnpj_companhia = '<CNPJ>'
  AND ipe_docs_fts MATCH 'aquisicao AND controle'
ORDER BY rank
LIMIT 20;
```

---

## Comportamento esperado ao pesquisar (regras de resposta)

1. **Sempre resolva o CNPJ primeiro** via `companies` antes de qualquer query.
2. **Verifique `texto_extraido`**: se `NULL`, exiba o `link_download` e informe que o conteúdo não foi extraído ainda.
3. **Para resumir assembleias**: leia `texto_extraido` e destaque deliberações sobre remuneração, mudanças estatutárias, eleição de conselho, aprovação de contas.
4. **Para fatos relevantes**: classifique o impacto — M&A, guidance, regulatório, operacional, financeiro.
5. **Para insider trading**: correlacione compras/vendas com fatos relevantes próximos e recompras vigentes.
6. **Para financeiros (DRE/Balanço)**: use `vw_dre` e `vw_balanco` primeiro. Se vierem NULL, olhe `plano_contas`: `banco` →
   `vw_dre_financeiro`, `seguradora` → `vw_dre_seguradora` (não decida pelo `companies.setor`). Nunca leia 3.05/3.07/3.11 de um
   banco ou seguradora como EBIT/EBT/lucro do plano padrão. Para contas específicas não nas views, consulte
   `demonstrativos_contabeis` diretamente filtrando por `cd_conta`.
7. **Para "esse número foi reapresentado?"**: consulte `consistency_flags` (Camada 2) filtrando por
   `cnpj_companhia`, `tipo_doc` e `periodo_fim`. Apresente sempre o valor original (`valor_ref`) e o
   reapresentado (`valor_cmp`) lado a lado — o padrão do banco é o original, nunca substituir.
8. **Antes de somar sublinhas de um demonstrativo** (ex: abrir o ativo circulante por conta): confira em
   `consistency_flags` (Camada 1) se o pai tem `nao_detalhado` — nesse caso use o valor do pai, não a soma
   dos filhos, que é zero. Um `divergencia`/`divergencia_formula` no documento é sinal de que o quadro
   está inconsistente na própria fonte; informe ao usuário e mostre pai e soma lado a lado.
9. **Documente documentos sem texto**: liste-os ao final com data + assunto + link, informando que precisam de extração manual se forem críticos.
10. **Quando uma conta "some" entre dois filings** (ex: existia no DFP, não está no ITR seguinte): consulte a Camada 3
    para o par. `renumerado` dá o novo código; `reclassificado_em_outros`/`reclassificado_em_irmao` dizem onde o valor
    foi parar; `divergencia_nao_explicada` exige olhar a Camada 2 do mesmo par (reapresentação) antes de concluir.
11. **Série histórica de uma conta criada pela empresa (`st_conta_fixa = 'N'`)**: antes de montar a série por `cd_conta`,
    confira em `cd_conta_ds_timeline` se o código foi renumerado ou reformulado no período; monte a série pelo nome
    normalizado (`ds_conta_norm`) + pai, seguindo `cd_conta_anterior`, e informe os anos em que a linha foi `ambiguo` ou `removida`.
12. **Para valores trimestrais (4T da DRE, qualquer trimestre da DFC/DVA)**: use `demonstrativos_trimestrais` com
    `safra = 'original'` por padrão, nunca subtraia acumulados à mão misturando `Último` e `Penúltimo`. Mostre `origem` e a
    `flag`: `reapresentacao_intra_ano` significa que publicado e derivado divergem (apresente os dois); `linha_sem_par`/`sem_3t`
    significa que o trimestre não pôde ser derivado para aquela conta; `par_ambiguo` significa que a linha mudou de nome o
    bastante para o casamento ficar duvidoso e o valor foi deliberadamente não calculado (o candidato está no `detalhe` da
    flag `layer = 6`); `reclassificacao_entre_filings` significa que o valor mistura dois layouts: avise que a linha está
    distorcida (em geral as linhas-irmãs se compensam e o pai está certo), mostre o total do pai e, se a safra reapresentado do mesmo
    trimestre não tiver a flag, apresente-a ao lado. Em contas criadas pela empresa (`st_conta_fixa = 'N'`), cite `cd_conta_b` e `casamento` ao apresentar
    o número: eles dizem qual linha do filing anterior entrou na subtração.

