# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras (CVM/B3).
Banco: SQLite local · 56 empresas · fontes IPE + VLMO + Recompra + FRE + DFP/ITR.
Atualização: manual via scripts de ingestão (ver seção "Conexão e atualização manual").

## Configuração do MCP (ler antes de começar)

Para o Claude acessar o banco, o MCP `postgres-local` precisa estar conectado.
Setup completo em `README.md`. Resumo rápido:

```bash
# 1. Criar banco e configurar .env
bash setup.sh                          # cria cvm_research.db
echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env

# 2. MCP no Claude Code
claude mcp add postgres-local -s user -- $(which npx) \
  -y @modelcontextprotocol/server-sqlite \
  $(pwd)/cvm_research.db

# 3. MCP no Claude desktop app
# Editar: ~/Library/Application Support/Claude/claude_desktop_config.json
# Adicionar:
# "mcpServers": {
#   "postgres-local": {
#     "command": "/caminho/absoluto/do/npx",
#     "args": ["-y", "@modelcontextprotocol/server-sqlite", "/caminho/absoluto/cvm_research.db"]
#   }
# }
# Reiniciar o app após editar.
```

**Verificar conexão** — peça ao Claude: *"Quantas linhas tem a tabela ipe_docs?"*
Se responder com número, o MCP está funcionando.

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
`dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta (em R$ — já normalizado MIL×1000)`

**Views prontas (preferir sobre query direta):**
- `vw_dre` — DRE resumida: `receita_liquida, custo_bens_servicos, resultado_bruto, ebit, resultado_financeiro, ebt, lucro_liquido`
- `vw_balanco` — BPA + BPP: `ativo_total, ativo_circulante, caixa, divida_curto_prazo, divida_longo_prazo, patrimonio_liquido`

⚠️ Bancos e seguradoras usam plano COSIF — retornarão NULL nas views. Diagnóstico: `SELECT cnpj_companhia FROM vw_dre WHERE receita_liquida IS NULL GROUP BY 1`

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
7. **Documente documentos sem texto**: liste-os ao final com data + assunto + link, informando que precisam de extração manual se forem críticos.

## Defasagem dos dados

**IPE (documentos corporativos):** a CVM atualiza os ZIPs anuais **semanalmente, toda segunda-feira entre 8h00 e 8h30**. Documentos divulgados após a última atualização (ex: fatos relevantes publicados durante a semana) só estarão disponíveis na base após a próxima segunda-feira.

Se um documento recente não aparecer na base, informar ao usuário:
- A base tem delay de até 7 dias para metadados do IPE
- O documento pode ser consultado diretamente no portal da CVM: `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`
- Rodar `python ingest_ipe.py` após a segunda-feira atualiza a base

**VLMO / FRE / Recompra / DFP / ITR:** sem atualização automática — rodar manualmente quando necessário.

## Monitorar uso do banco
```sql
SELECT COUNT(*) AS total_docs FROM ipe_docs;
```

## Conexão e atualização manual

**Banco:** SQLite local (`cvm_research.db`), MCP `postgres-local` conectado.
**Setup completo:** ver `README.md`. Setup rápido: `bash setup.sh`.

### MCP — Claude Code (terminal)

```bash
claude mcp add postgres-local -s user -- $(which npx) \
  -y @modelcontextprotocol/server-sqlite \
  $(pwd)/cvm_research.db

# Verificar:
claude mcp list   # deve mostrar ✓ Connected
```

### MCP — Claude desktop app (chat visual)

Editar `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "postgres-local": {
      "command": "/caminho/absoluto/do/npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-sqlite",
        "/caminho/absoluto/para/cvm_research.db"
      ]
    }
  }
}
```

Obter o caminho do npx: `which npx`. Obter o caminho absoluto do banco: `pwd`/cvm_research.db. Reiniciar o app após salvar.

### Atualização manual dos dados

Rodar periodicamente para manter a base em dia:

```bash
cd scripts/ingest
source ../../.venv/bin/activate

python ingest_ipe.py        # metadados de documentos
python ingest_vlmo.py       # insider trading
python ingest_recompra.py   # programas de recompra
python ingest_fre.py        # dados de capital, acionistas, remuneração
python ingest_dfp.py        # demonstrativos anuais (ano corrente e anterior)
python ingest_itr.py        # demonstrativo trimestral (ano corrente)

# Trimestral — reprocessa toda a série histórica
python ingest_dfp.py --historico
python ingest_itr.py --desde 2016
```

O `.env` na raiz do projeto deve ter:
```
DATABASE_URL=sqlite:///cvm_research.db
```

**Nota:** `extract_pdf.py` requer Supabase e não foi migrado para SQLite. Para
extração de texto de PDFs, continue usando o banco Supabase + as variáveis
SUPABASE_URL/SUPABASE_KEY no `.env`.

**⚠️ Migração de dados existentes:** O campo `texto_extraido` (texto extraído de PDFs)
**não é transferido automaticamente** ao migrar do PostgreSQL para SQLite. Após a
migração, o banco SQLite inicia vazio. Todos os metadados de documentos são
re-ingeridos pelos ingestores (IPE, VLMO, etc.), mas o texto extraído de PDFs
requer re-execução do `extract_pdf.py` contra um banco Supabase. Guarde suas
credenciais `SUPABASE_URL`/`SUPABASE_KEY` se quiser recuperar o conteúdo extraído.

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
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
