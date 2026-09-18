# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras (CVM/B3).
Banco: SQLite local (`cvm_research.db`, ~12 GB) · 145 empresas · fontes IPE (2015+) + VLMO (2018+) + Recompra + FRE (2010+) + DFP (2010+) / ITR (2011+) + Notas Explicativas (sob demanda).
Atualização: `bash scripts/update_weekly.sh` (manual) ou job launchd toda segunda 9h (`scripts/install_weekly_launchd.sh`).

## Acesso ao banco (MCP `cvm-research`)

O Claude consulta o banco pelo MCP `cvm-research` (`scripts/mcp/cvm_mcp.py`, stdio, somente leitura).
Ferramentas: `query(sql)` (SELECT, até 500 linhas), `list_tables()`, `describe_table(nome)`.
Setup e troubleshooting: ver `INSTALL.md`. Verificação rápida: *"Quantas linhas tem a tabela ipe_docs?"* deve responder um número acima de 160.000.

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

**tipo_cargo relevantes:** `'Conselho de Administração ou Vinculado'`, `'Diretor ou Vinculado'`, `'Controlador ou Vinculado'`
**tipo_movimentacao compras:** `'Compra à vista'`, `'Compra à termo'`, `'Compra'`, `'Posse'`, `'Saldo Inicial'`
**tipo_movimentacao vendas:** `'Venda à vista'`, `'Venda à termo'`, `'Venda'`, `'Desligamento/saída'`, `'Saldo Final'`

### `vlmo_posicao` — posição consolidada de valores mobiliários (por documento)
`protocolo_entrega (PK), cnpj_companhia, data_referencia, categoria, tipo, link_download`

### `recompra_programas` — programas de recompra de ações
`id_programa (PK), cnpj_companhia, finalidade_compra, data_deliberacao,`
`motivo, data_final_prazo, situacao ('Em Andamento'/'Encerrado')`

⚠️ `recompra_quantidades` e `recompra_intermediarios` existem no schema mas estão **vazias** — o ingestor ainda não as popula. Não use.

### `fre_capital_social` — composição do capital social (histórico)
`cnpj_companhia, data_referencia, tipo_capital, data_autorizacao_aprovacao,`
`valor_capital, quantidade_acoes_ordinarias, quantidade_acoes_preferenciais, quantidade_total_acoes`

### `fre_remuneracao_orgao` — remuneração dos administradores por órgão
`cnpj_companhia, data_referencia, orgao_administracao, numero_membros,`
`numero_membros_remunerados, valor_maior_remuneracao, valor_menor_remuneracao, valor_medio_remuneracao`

### `fre_posicao_acionaria` — principais acionistas
`cnpj_companhia, data_referencia, acionista, acionista_controlador,`
`percentual_acao_ordinaria_circulacao, percentual_acao_preferencial_circulacao, percentual_total_acoes_circulacao`

### `demonstrativos_contabeis` — DFP (anual) e ITR (trimestral) estruturados
`cnpj_companhia, fonte ('DFP'/'ITR'), tipo_doc ('BPA'/'BPP'/'DRE'/'DFC_MI'/'DVA'),`
`data_referencia, versao, ordem_exercicio ('Último'/'Penúltimo'),`
`dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta (em R$ — já normalizado MIL×1000),`
`st_conta_fixa ('S' = conta padrão CVM, 'N' = criada pela empresa)`

**Views prontas (preferir sobre query direta):**
- `vw_dre` — DRE resumida: `receita_liquida, custo_bens_servicos, resultado_bruto, ebit, resultado_financeiro, ebt, lucro_liquido`
- `vw_balanco` — BPA + BPP: `ativo_total, ativo_circulante, caixa, divida_curto_prazo, divida_longo_prazo, patrimonio_liquido`

**Períodos no ITR:** no 2T e 3T a DRE tem duas linhas por conta — trimestre isolado
(`dt_ini_exerc` = início do trimestre) e acumulado no ano (`dt_ini_exerc` = início do
exercício). `vw_dre` devolve o trimestre isolado; `vw_dre_acumulada` devolve o acumulado.
DFC_MI e DVA só têm acumulado no ITR. BPA/BPP têm `dt_ini_exerc` NULL (posição na data).
Ao consultar `demonstrativos_contabeis` direto para DRE de ITR, filtre `dt_ini_exerc`,
senão as linhas dobram.

⚠️ Bancos e seguradoras usam plano COSIF — retornarão NULL nas views. Diagnóstico: `SELECT cnpj_companhia FROM vw_dre WHERE receita_liquida IS NULL GROUP BY 1`

### `notas_explicativas` — texto completo do ITR/DFP (com notas explicativas)
`cnpj_companhia, fonte ('ITR'/'DFP'), data_referencia, versao,`
`numero_sequencial_documento, link_download, texto_extraido (NULL = não extraído),`
`extracao_falhou, chars_extraidos`

Diferença para `demonstrativos_contabeis`: aquela tabela só tem os quadros
padronizados (BPA/BPP/DRE/DFC_MI/DVA); esta tem o **PDF completo do documento**,
incluindo notas explicativas (movimentação de Imobilizado/Intangível/Direito de
Uso, provisões, etc.) — dado que não existe em nenhum feed estruturado da CVM.
Populada sob demanda via `ingest_notas_explicativas.py` (não faz parte do fluxo
semanal automático — ver script para detalhes). **Cobertura é mínima**: antes de
consultar, verifique com `SELECT cnpj_companhia, fonte, data_referencia FROM notas_explicativas`
se a empresa/período já foi ingerido; se não, informe o comando para ingerir. Busca full-text via
`notas_explicativas_fts` (mesmo padrão de `ipe_docs_fts`).

⚠️ Diferente dos demais ingestores (que baixam ZIPs anuais de `dados.cvm.gov.br`),
este busca cada documento individualmente em `rad.cvm.gov.br` (o portal de
consulta de documentos da CVM, não o feed de dados abertos) — mais lento e mais
sensível a rate limit, por isso o `time.sleep(0.5)` entre documentos e o
`--limite` default de 20. Além disso, ao contrário de `demonstrativos_contabeis`
(que guarda todas as versões), aqui só a versão mais recente é mantida — uma
reapresentação (nova `versao`) descarta o `texto_extraido` da versão anterior.

### `consistency_flags` — achados de consistência dos demonstrativos (metadados, não valores)
`run_id, layer, check_type, classificacao, severity ('info'/'warn'/'error'), cnpj_companhia, tipo_doc,`
`cd_conta (NULL = resumo do par de documentos), cd_conta_pai, ds_conta, periodo_ini ('NA' em BPA/BPP), periodo_fim,`
`fonte_ref, data_ref, ordem_ref (filing baseline), fonte_cmp, data_cmp, ordem_cmp (filing comparado),`
`valor_ref, valor_cmp, diff_abs (cmp − ref), diff_rel, detalhe (JSON)`

Gerada por `scripts/analysis/`. As Camadas 1, 2 e 3 rodam no job semanal (`update_weekly.sh`) logo após
`ingest_dfp`/`ingest_itr`, na base inteira; também podem ser rodadas à mão por empresa.
Nunca altera `demonstrativos_contabeis`: o valor publicado pela CVM fica intacto e aqui ficam os metadados.
A tabela guarda **a última execução de cada escopo** `(layer, check_type, cnpj[, tipo_doc])`; o histórico
de execuções está em `consistency_runs` (`run_id, layer, check_type, escopo, started_at, finished_at,
total_checked, total_flagged, script_args`).

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

**Camada 2 (`layer = 2`, `check_type = 'cross_period'`)** — o mesmo período aparece em até 5 filings
(BPA 31/12/Y: DFP(Y) Último, ITR 1T/2T/3T(Y+1) Penúltimo, DFP(Y+1) Penúltimo). O baseline é sempre o
filing mais antigo (o original, como reportado na época) e cada filing posterior é comparado a ele:
- `reapresentacao` (`warn`): a conta-total do tipo_doc (`1`, `2`, `3.01`/`3.11`, `6.05`, "Valor Adicionado
  Total a Distribuir") diverge acima da tolerância `max(R$ 1.000, 1% × |ref|)`; todas as linhas
  divergentes do par herdam a classe.
- `reclassificacao` (`info`): totais batem, mas alguma sublinha diverge (mudou de conta).
- Linha que existe só num dos filings **não** gera flag aqui (é a Camada 3); só entra nas contagens do
  resumo do par (`detalhe = {"linhas_comuns", "linhas_divergentes", "linhas_exclusivas_ref",
  "linhas_exclusivas_cmp", "total_disponivel"}`).

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

Para rodar: `cd scripts/analysis && python run_all.py --layer 2,3 --cnpj <CNPJ>` (ou `--full` para a base).

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
SELECT data_referencia, data_movimentacao, tipo_cargo, tipo_movimentacao,
       tipo_ativo, caracteristica, quantidade, preco_unitario, volume
FROM vlmo_movimentacoes
WHERE cnpj_companhia = '<CNPJ>'
  AND tipo_movimentacao IN (
      'Compra à vista', 'Compra à termo', 'Compra',
      'Venda à vista', 'Venda à termo', 'Venda'
  )
ORDER BY data_movimentacao DESC
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
  AND v.tipo_movimentacao IN ('Compra à vista', 'Compra à termo', 'Compra',
                             'Venda à vista', 'Venda à termo', 'Venda')
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
SELECT data_referencia, acionista, acionista_controlador,
       percentual_acao_ordinaria_circulacao  AS pct_on,
       percentual_acao_preferencial_circulacao AS pct_pn,
       percentual_total_acoes_circulacao     AS pct_total
FROM fre_posicao_acionaria
WHERE cnpj_companhia = '<CNPJ>'
ORDER BY data_referencia DESC, percentual_total_acoes_circulacao DESC NULLS LAST
LIMIT 20;
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

## Comportamento esperado ao pesquisar

1. **Sempre resolva o CNPJ primeiro** via `companies` antes de qualquer query.
2. **Verifique `texto_extraido`**: se `NULL`, exiba o `link_download` e informe que o conteúdo não foi extraído ainda.
3. **Para resumir assembleias**: leia `texto_extraido` e destaque deliberações sobre remuneração, mudanças estatutárias, eleição de conselho, aprovação de contas.
4. **Para fatos relevantes**: classifique o impacto — M&A, guidance, regulatório, operacional, financeiro.
5. **Para insider trading**: correlacione compras/vendas com fatos relevantes próximos e recompras vigentes.
6. **Para financeiros (DRE/Balanço)**: use `vw_dre` e `vw_balanco` primeiro. Se NULL nos campos chave, verifique se a empresa é banco/seguradora (COSIF). Para contas específicas não nas views, consulte `demonstrativos_contabeis` diretamente filtrando por `cd_conta`.
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

## Defasagem dos dados

**IPE (documentos corporativos):** a CVM atualiza os ZIPs anuais **semanalmente, toda segunda-feira entre 8h00 e 8h30**. Documentos divulgados após a última atualização (ex: fatos relevantes publicados durante a semana) só estarão disponíveis na base após a próxima segunda-feira.

Se um documento recente não aparecer na base, informar ao usuário:
- A base tem delay de até 7 dias para metadados do IPE
- O documento pode ser consultado diretamente no portal da CVM: `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`
- Rodar `python ingest_ipe.py` após a segunda-feira atualiza a base

**VLMO / FRE / Recompra / DFP / ITR / consistência (Camada 2):** entram no mesmo job semanal (`scripts/update_weekly.sh`). Para forçar agora: `bash scripts/update_weekly.sh`. Logs em `logs/update_*.log`.

## Anomalias conhecidas: `data_referencia` no futuro em `ipe_docs`

Existem registros em `ipe_docs` com `data_referencia` posterior à data atual. **Não filtre isso de forma genérica** (ex: `WHERE data_referencia <= date('now')`) — a maioria é legítima:

- **~96% dos casos** (categorias `Calendário de Eventos Corporativos` e `Assembleia`) são documentos que citam datas de eventos *futuros* por natureza: um calendário de eventos corporativos lista datas de divulgações ainda não ocorridas; uma convocação de assembleia é publicada com a data da própria assembleia, que ainda vai acontecer. Isso é dado correto, não erro.
- **Uma fração pequena é erro de digitação na fonte da CVM**, confirmado comparando o CSV oficial (`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_<ano>.zip`) diretamente — o erro já vem no `Data_Referencia` da CVM, inclusive embutido no `Protocolo_Entrega` gerado pelo sistema deles (ex: protocolo `001023IPE07072121...` para uma data `2121-07-07`, quando a `data_entrega` real foi `2021-07-30`). **Não é bug do `ingest_ipe.py`** (ele usa `pd.to_datetime` puro, sem lógica de correção de ano) — é erro de digitação no momento do registro do documento na CVM.

**Como distinguir um caso legítimo de um erro real:** compare `data_referencia` com `data_entrega` (que é sempre confiável — é o timestamp de recebimento pela CVM). Gap de 0–1 ano é normal (evento agendado para o mesmo ano ou o seguinte). Gap ≥ 9 anos é sinal de erro de digitação na fonte:

```sql
SELECT data_referencia, data_entrega, cnpj_companhia, categoria, protocolo_entrega,
  (CAST(substr(data_referencia,1,4) AS INTEGER) - CAST(substr(data_entrega,1,4) AS INTEGER)) AS gap_anos
FROM ipe_docs
WHERE data_referencia > date('now')
  AND (CAST(substr(data_referencia,1,4) AS INTEGER) - CAST(substr(data_entrega,1,4) AS INTEGER)) >= 9
ORDER BY gap_anos DESC;
```

Quando aparecer um novo caso assim (gap ≥ 9 anos): não tentar "corrigir" o ano automaticamente (não há offset consistente — já vimos +100, +71, +16, +9 anos no mesmo padrão de erro), apenas reportar ao usuário citando `data_entrega` como a data confiável e, se necessário, o `link_download` para conferência manual no portal da CVM.

## Monitorar uso do banco
```sql
SELECT COUNT(*) AS total_docs FROM ipe_docs;
```

## Conexão e atualização manual

**Banco:** SQLite local (`cvm_research.db`) via MCP `cvm-research`. Setup completo em `INSTALL.md`; setup rápido: `bash setup.sh`.

### Atualização dos dados

Automática: `bash scripts/install_weekly_launchd.sh` (segunda 9h; `--status` mostra o último log).
Manual, tudo de uma vez: `bash scripts/update_weekly.sh`. Passo a passo:

```bash
cd scripts/ingest
source ../../.venv/bin/activate

python ingest_ipe.py        # metadados de documentos
python ingest_vlmo.py       # insider trading
python ingest_recompra.py   # programas de recompra
python ingest_fre.py        # dados de capital, acionistas, remuneração
python ingest_dfp.py        # demonstrativos anuais (ano corrente e anterior)
python ingest_itr.py        # demonstrativo trimestral (ano corrente)

# Histórico completo — rode uma vez ao migrar ou adicionar novas empresas
python ingest_ipe.py   --desde 2015   # IPE útil a partir de 2015 (ZIPs 2009–2014 vêm sem protocolo → 0 docs)
python ingest_dfp.py   --historico --desde 2010   # DFP desde 2010
python ingest_itr.py   --desde 2011   # ITR desde 2011
python ingest_vlmo.py  --desde 2018   # VLMO estruturado disponível desde 2018
# Notas explicativas: sem --historico por padrão — cada PDF tem dezenas de MB
# e centenas de empresas × anos vira um volume grande. Rodar sob demanda por
# empresa/ano quando precisar de um dado que só existe em nota (ex: quebra de
# depreciação por classe de ativo), como em:
#   python ingest_notas_explicativas.py --cnpj <CNPJ> --ano <ANO> --fonte ITR
python ingest_fre.py   --desde 2010   # FRE desde 2010
```

O `.env` na raiz do projeto deve ter:
```
DATABASE_URL=sqlite:///cvm_research.db
```

**Extração de texto de PDFs:** `extract_pdf.py` funciona diretamente com o banco SQLite.
Para popular `texto_extraido`, rode `python extract_pdf.py` com o DATABASE_URL configurado.

### Adicionar empresas à watchlist

O `watchlist.csv` controla quais empresas são ingeridas. Para expandir a cobertura:

```bash
cd scripts/ingest
source ../../.venv/bin/activate

# 1. Gerar/atualizar o catálogo B3+CVM (company_catalog.csv na raiz do projeto)
python catalog.py

# 2. Buscar uma empresa por nome ou ticker
python catalog.py --search "petrobras"

# 3. Adicionar empresas ao watchlist.csv
python add_companies.py --ibov          # Todas as empresas do IBOV atual
python add_companies.py --ibov --dry-run  # Preview sem gravar
python add_companies.py --all           # Todas as ~443 empresas B3 ativas
python add_companies.py --ticker VALE3  # Uma empresa específica
python add_companies.py --setor "Saude" # Por setor CVM (parcial, case-insensitive)
python add_companies.py --ibov --skip-assumed  # Pula tickers inferidos (sufixo 3)

# 4. Sincronizar watchlist.csv → tabela companies
python ingest_companies.py

# 5. Re-rodar ingestores com histórico completo para as novas empresas
# (os ZIPs já foram baixados — re-download é inevitável mas sem código novo)
python ingest_ipe.py --desde 2015
python ingest_dfp.py --historico --desde 2010
# ... etc
```

**Tickers assumidos:** empresas fora do IBOV recebem ticker com sufixo "3" (ON).
Checar coluna `observacao` no watchlist.csv para linhas com `auto:assumed` e corrigir
o ticker se necessário antes de rodar `ingest_companies.py`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /code-review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
