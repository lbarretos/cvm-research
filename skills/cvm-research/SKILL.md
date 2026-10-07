---
name: cvm-research
description: Pesquisa em documentos, eventos e demonstrações financeiras de empresas abertas brasileiras (B3/CVM) numa base SQLite local acessada pelo MCP cvm-research. Use esta skill para QUALQUER pergunta sobre fatos relevantes, assembleias (AGO/AGE), atas de conselho, comunicados ao mercado, releases de resultado, dividendos/JCP, insider trading (VLMO), programas de recompra, composição acionária, remuneração de administradores, DRE/balanço/fluxo de caixa (DFP/ITR), série trimestral com 4T, reapresentações de balanço ou notas explicativas. Acione sempre que o usuário citar um ticker brasileiro (PETR4, WEGE3…), o nome de uma companhia aberta, "CVM", "RAD", "B3", ou pedir para exportar esses dados para Excel, mesmo que não diga "CVM" e mesmo que a empresa ainda não esteja na base (a skill faz o onboarding).
---

# CVM Research

Base local de documentos e eventos de companhias abertas brasileiras. Fontes: IPE (documentos
com texto dos PDFs), VLMO (insiders), Recompra, FRE (capital, acionistas, remuneração), DFP/ITR
(demonstrações estruturadas, com camadas de consistência e série trimestral) e notas explicativas.

- **Projeto:** `/Users/lucasbarreto/Documents/Coding/cvm-research` (Python em `.venv/bin/python`)
- **Banco:** `cvm_research.db` (SQLite). Consulte **só pelo MCP `cvm-research`**, nesta ordem:
  1. `resolve_company(texto)` para achar a empresa (ticker, nome ou CNPJ → CNPJ; avisa se não está na base);
  2. as views prontas (`vw_dre`, `vw_balanco`, `demonstrativos_trimestrais`…) e as receitas de
     `references/receitas-sql.md` por `query(sql)`;
  3. **Conteúdo de documentos**: `search_docs(consulta, ticker?, categorias?, desde?, ate?)` devolve os melhores
     trechos (FR, CM, AVI, RCA, assembleias, press-release; versões vigentes, sem repetição) e `read_doc(protocolo,
     ordem)` lê a partir do trecho, em até 28 mil caracteres, com `proximo_ordem` para continuar. Prefira-as ao FTS
     por documento (seção 5) e a `substr(texto_extraido…)`;
  4. `list_tables()`/`describe_table(nome)` só se faltar saber uma coluna.
  A saída é tabular `{colunas, linhas, aviso?}`; cada resposta cabe em 30 mil caracteres e o `aviso`
  diz quando foi cortada. Se as ferramentas não aparecerem, carregue com `ToolSearch`
  (`select:mcp__cvm-research__query,...`); se o servidor não existir, aponte o `INSTALL.md` do projeto.
- **Cobertura:** varia por instalação. Não afirme números de memória; se precisar, rode
  `SELECT COUNT(*) FROM companies`.

## O banco é SQLite, não Postgres

Os erros mais comuns vêm de escrever SQL de Postgres. Traduza assim:

| Não funciona | Use |
|---|---|
| `ILIKE '%x%'` | `LIKE '%x%'` (já ignora caixa em ASCII; com acento, busque pelo trecho sem acento ou use FTS) |
| `CURRENT_DATE - INTERVAL '1 year'` | `date('now','-1 year')` |
| `data::date`, `TO_CHAR`, `DATE_TRUNC('month', d)` | datas já são TEXT `YYYY-MM-DD`; mês = `substr(d,1,7)` |
| `LEFT(txt, 500)` | `substr(txt, 1, 500)` |
| `to_tsquery` / `search_vector` | tabela FTS5 `ipe_docs_fts` com `MATCH` (seção 5) |
| `detalhe->>'x'` | `json_extract(detalhe, '$.x')` |

O MCP corta qualquer célula acima de 25 mil caracteres (marca `…[truncado: N chars]`) e aborta
consultas acima de 20 s. `texto_extraido` chega a 12 milhões de caracteres: leia com
`substr(texto_extraido, inicio, 20000)` ou `snippet()`, não com `SELECT texto_extraido` puro.

## Fluxo de pesquisa

### 0. A base cobre o período?

Se a pergunta envolve os últimos 30 dias ("essa semana", "o último fato relevante", "hoje"),
rode `SELECT MAX(data_entrega) FROM ipe_docs` antes de tudo. Nada encontrado depois dessa data
significa **sem dado**, não "não houve": diga isso e aponte o RAD
(`https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`). A CVM atualiza o IPE às segundas;
defasagem acima de 9 dias indica que o job semanal falhou (ver `references/manutencao.md`).
O VLMO tem defasagem estrutural de ~1 mês (o formulário é entregue até o dia 10 do mês seguinte).

### 1. Escopo

Extraia do pedido: empresa, período, categorias e foco. Só pergunte (AskUserQuestion) o que
faltar e mudar o resultado; um pedido como "fatos relevantes da WEG no último ano" já tem tudo.

Categorias (`ipe_docs.categoria`, e `tipo` quando indicado):

| Atalho | Filtro |
|---|---|
| FR | `categoria = 'Fato Relevante'` |
| AGO / AGE | `categoria = 'Assembleia'` e `tipo IN ('AGO','AGE','AGO/E')` (AGO/E é a assembleia conjunta, a mais comum em abril; `AGDEB` é de debenturistas) |
| RCA | `categoria = 'Reunião da Administração'` (atas de conselho: dividendos, JCP, recompra costumam estar aqui) |
| CM | `categoria = 'Comunicado ao Mercado'` |
| AVI | `categoria = 'Aviso aos Acionistas'` |
| RES | `categoria = 'Dados Econômico-Financeiros' AND tipo = 'Press-release'` (não existe categoria "Resultado") |
| DF em PDF | mesma categoria, `tipo` = `'Demonstrações Financeiras Intermediárias'` / `'... Anuais Completas'` |

`especie` diz qual documento é: numa assembleia, `Proposta da Administração` (o que foi proposto),
`Ata` e `Sumário das Decisões` (o que foi aprovado), `Mapa final de votação` (quantos votaram contra),
`Edital de Convocação`, `Boletim de voto a distância`, `Manual para participação`.

Período: `6m` → `date('now','-6 months')`; `1a` → `date('now','-1 year')`; `2024` →
`BETWEEN '2024-01-01' AND '2024-12-31'`. "Último trimestre" = últimos 3 meses corridos; se não
coincidir com um trimestre fechado, diga qual recorte usou. Filtre por `data_entrega` (quando o
mercado soube); `data_referencia` de assembleias e calendários aponta para o evento, muitas vezes
futuro, e em alguns documentos vem com o ano errado na fonte.

### 2. Empresa → CNPJ

Todo filtro de dados usa CNPJ, nunca ticker ou nome. **Use `resolve_company`**: ela já tenta o ticker
exato, a raiz (ITUB3 → ITUB4), o nome sem acento e o CNPJ, e devolve aviso quando há mais de uma empresa
ou nenhuma. O SQL abaixo é o que ela faz por dentro.

```sql
SELECT cnpj, ticker, nome_cvm, setor FROM companies WHERE ticker = 'WEGE3';
SELECT cnpj, ticker, nome_cvm, setor FROM companies WHERE nome_cvm LIKE '%weg%';
```

`companies` guarda **um ticker por empresa** (PETR4, não PETR3; ITUB4, não ITUB3). Se o ticker
exato não achar nada, tente a raiz antes de concluir qualquer coisa:
`WHERE substr(ticker,1,4) = substr('<TICKER>',1,4)`, e depois o nome. ON, PN e UNIT são o mesmo CNPJ.

Mais de um resultado (Itaú Unibanco × Itaúsa, Copasa × Sabesp num `LIKE '%sanea%'`): confirme com o
usuário ou declare a premissa. Nenhum resultado nem pela raiz: a empresa não está na base. Se a
pergunta é sobre os últimos dias, aponte o RAD primeiro (a carga não resolveria a recência); senão
ofereça o onboarding de `references/manutencao.md`. Não dispare a carga sem um "sim": baixa ZIPs
anuais inteiros e leva de minutos a horas.

### 3. Inventário

```sql
SELECT protocolo_entrega, data_entrega, data_referencia, categoria, tipo, assunto,
       texto_extraido IS NOT NULL AS tem_texto, extracao_falhou, chars_extraidos, link_download
FROM ipe_docs
WHERE cnpj_companhia = '<CNPJ>'
  AND categoria IN ('Fato Relevante')           -- omitir se "todas"
  AND data_entrega >= date('now','-1 year')
ORDER BY data_entrega DESC;
```

Apresente contagem ("X com texto, Y sem texto"). O mesmo documento pode vir em várias entregas
(reapresentação: mesmo `assunto` e `data_referencia`, `data_entrega` diferente): trate a mais
recente como vigente e mencione que houve reapresentação. Se a vigente não tem texto e uma
anterior tem, use a anterior e avise que pode haver diferença.

### 4. Documentos sem texto

A cobertura de texto varia muito por empresa (quase 100% nas antigas, ~6% numa empresa recém-
adicionada). Antes de prometer leitura, meça:
`SELECT ROUND(AVG(texto_extraido IS NOT NULL)*100) FROM ipe_docs WHERE cnpj_companhia = '<CNPJ>'`.
Para os documentos sem texto, ofereça extrair (comando em `references/manutencao.md`;
`--rebuild-fts` no fim é obrigatório, senão a busca não enxerga o texto novo) e responda com o que
os dados estruturados permitem, sem inventar o conteúdo. `extracao_falhou = 1` costuma ser PDF
escaneado ou link quebrado: liste o `link_download` para leitura manual.

Sequências como `(cid:16)(cid:26)(cid:20)` são páginas de PDF com fonte embutida sem mapa de
caracteres: não há texto recuperável ali (os casos de acentuação trocada já foram reparados). Se a
busca FTS vier vazia num tema que deveria existir, tente `assunto LIKE` antes de concluir que não há.

### 5. Análise do conteúdo

**Busca por tema.** Use `search_docs` (trechos de ~2 mil caracteres, só camada quente, só versões vigentes) e
`read_doc` para ler em volta. O que não está na camada quente (DFs completas, prospectos, agente fiduciário) e
os documentos substituídos só saem do FTS por documento abaixo; `search_docs(versoes_antigas=True)` inclui as
substituídas. Sem trecho encontrado, tente menos termos ou prefixo (`aquisi*`) antes de concluir que não há.

**Busca por documento — FTS5.** O índice ignora acento e caixa (`aquisição` = `aquisicao`), aceita
prefixo (`dividend*`), frase (`"juros sobre capital"`), `AND`/`OR`/`NOT`, `NEAR(a b, 10)` e
filtro de coluna (`assunto: incorporacao`). `snippet()` devolve o trecho onde o termo aparece.

```sql
SELECT i.protocolo_entrega, i.data_entrega, i.categoria, i.assunto,
       snippet(ipe_docs_fts, 3, '**', '**', ' … ', 40) AS trecho
FROM ipe_docs_fts
JOIN ipe_docs i ON i.rowid = ipe_docs_fts.rowid
WHERE ipe_docs_fts MATCH 'dividend* AND "juros sobre capital"'
  AND i.cnpj_companhia = '<CNPJ>'
  AND i.data_entrega >= date('now','-1 year')
ORDER BY bm25(ipe_docs_fts)
LIMIT 20;
```

Para nomes próprios (concessão, contraparte, produto), `assunto LIKE '%nome%'` é mais preciso.

**Leitura.** Trecho não basta para concluir; leia o documento. Fatos relevantes e comunicados
cabem inteiros. Atas de AGO e DFs passam de 150 mil caracteres: leia em janelas com
`substr(texto_extraido, inicio, 20000)` ou vá direto ao ponto com
`instr(texto_extraido, 'termo')` para achar o offset.

**Como analisar cada categoria:**
- **Fato Relevante**: classifique o impacto (M&A, guidance, regulatório, financeiro, operacional)
  e diga o que muda para o acionista.
- **Assembleia / RCA**: remuneração (proposta vs aprovada), reforma estatutária, eleição de
  conselho, destinação do lucro e dividendos, emissões e planos de incentivo.
- **Press-release**: receita, EBITDA, lucro, variação anual e guidance. Para números oficiais,
  prefira as demonstrações estruturadas (`references/demonstrativos.md`) e use o release para o
  que só existe nele (EBITDA ajustado, métricas operacionais). Empresas como a Vale divulgam o
  release em US$; a CVM tem os valores em R$.

**Dividendos e JCP.** Não há tabela estruturada de proventos: tudo sai do texto. Procure em
`Fato Relevante`, `Comunicado ao Mercado`, `Aviso aos Acionistas` e `Reunião da Administração`,
com um OR largo (cada empresa escreve de um jeito; a Petrobras usa "remuneração aos acionistas"):
`MATCH 'dividend* OR "juros sobre capital" OR provento* OR "remuneracao aos acionistas"'`, e
filtre depois pelo `assunto`. Deixe claro qual recorte usou, porque "aprovou em 2025" tem três
leituras: deliberado em 2025, relativo ao exercício de 2025 ou pago em 2025. Por deliberação,
traga data, valor total, valor por ação (ON/PN), data-base (ex-direito) e data de pagamento; diga
se o JCP é bruto e se o valor é corrigido pela Selic até o pagamento. Dividendo complementar do
exercício anterior costuma ser proposto em fevereiro/março e aprovado na AGO.

**Composição acionária e remuneração** (FRE): leia `references/fre.md` antes. As duas tabelas têm
armadilhas que dão número errado sem erro de SQL (cadeia de controle, unidades misturadas).

### 6. Dados complementares

Em pesquisa ampla sobre uma empresa, traga insider e recompra e diga "nenhum registro" quando
vier vazio — ausência também é informação.

- **Insider trading (VLMO):** leia `references/vlmo.md` antes da primeira query. Resumo: use só
  a última `versao` de cada formulário, filtre as operações por `data_movimentacao` (a data
  exata existe) e separe `Saldo Inicial` (posição) das operações.
- **Recompra:**
  ```sql
  SELECT data_deliberacao, finalidade_compra, motivo, data_final_prazo, situacao,
         quantidade_acoes_ordinarias AS qtd_on, quantidade_acoes_preferenciais AS qtd_pn
  FROM recompra_programas WHERE cnpj_companhia = '<CNPJ>'
  ORDER BY data_deliberacao DESC LIMIT 5;
  ```
  `recompra_quantidades` e `recompra_intermediarios` estão vazias; a execução do programa só
  aparece no VLMO (`tipo_cargo` da própria companhia/tesouraria) ou em comunicados.
- **Acionistas e remuneração:** `references/fre.md`.
- **Demonstrações financeiras, reapresentações, série trimestral, notas explicativas:**
  `references/demonstrativos.md`.

**Triangulação.** Insider comprando ou vendendo perto de um fato relevante, ou durante um
programa de recompra, é o sinal mais útil que a base produz. Com `data_movimentacao` dá para
usar janela de ±7 dias em torno de `data_entrega` do fato (query pronta em `references/vlmo.md`).
Muitas empresas publicam poucos fatos relevantes e anunciam coisas materiais como Comunicado ao
Mercado ou no release: se houver menos de ~5 FRs no período, amplie para essas categorias e diga
que ampliou. Se o insider opera quase todo mês, "perto de um fato" é quase inevitável; o sinal
está na ausência ou concentração de operações antes do fato, não na mera proximidade.

### 7. Resposta

```
### [Ticker] — [Nome] — [Período] — [Categorias]

**Resumo** — 3 a 6 bullets com os achados mais relevantes, primeiro o que muda a tese.

**Documentos** — X analisados, Y sem texto (listados no fim)
| Data entrega | Categoria | Assunto | Classificação | Destaque |

**Insider trading** (última versão de cada formulário, sem Saldo Inicial)
| Data | Cargo | Operação | Ativo/classe | Qtd | Preço médio | Volume (R$) |

**Recompra** — programas vigentes e se houve execução no período.

**Sem texto extraído** (se houver)
| Data | Categoria | Assunto | Link |
```

Cite a data da última carga quando o período pedido encosta no presente: a CVM atualiza os ZIPs
do IPE às segundas e a base pode estar até 7 dias atrás (`SELECT MAX(data_entrega) FROM ipe_docs`).
Documento mais novo que isso está no RAD: `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`.

**Excel.** Se o usuário quiser planilha, use a skill `xlsx` com os dados já tratados (última
versão, sem saldos) e salve em `~/Desktop/<TICKER>_<tema>_<período>.xlsx`, a não ser que ele
indique outro lugar.

## Regras

1. **Não invente conteúdo.** `texto_extraido` NULL → mostre o link, não resuma pelo assunto.
   Ausência de resultado depois da última carga é "sem dado", não "não aconteceu".
2. **Classifique, não só liste.** O valor está em dizer o que o documento significa.
3. **Valores publicados são o padrão.** Quando houver reapresentação, mostre original e
   reapresentado lado a lado; nunca troque um pelo outro em silêncio.
4. **Datas futuras em `ipe_docs.data_referencia`** são normais em Assembleia e Calendário de
   Eventos. Gap de 9+ anos para `data_entrega` é erro de digitação na CVM: cite `data_entrega`.
5. **Bancos e seguradoras**: `vw_dre` vem NULL com `plano_contas` = `'banco'` ou `'seguradora'`.
   Use `vw_dre_financeiro` ou `vw_dre_seguradora`. Decida pelo `plano_contas`, não por
   `companies.setor` (B3, Itaúsa, Caixa Seguridade e Porto são "Financeiro" mas usam o plano padrão).
6. **D&A (depreciação, amortização e exaustão) vem da DVA, conta `7.04.01`** (`tipo_doc = 'DVA'`), não da
   DFC: lá ela fica em linhas criadas pela empresa que variam e podem misturar impairment (CSAN3 2024: DVA
   R$ 7,02 bi; a soma das linhas "D&A" da DFC dava R$ 3,87 bi sem a baixa de R$ 3,16 bi). Mesmo que a DFC
   pareça ter a linha certa, use a DVA e, se divergir, mostre as duas.
7. **Lucro por ação (`3.99.*`)** está em R$/ação. Uns 20 filings trazem valores absurdos já na fonte
   (MRV ITR 2T17 com 614 milhões): se passar de algumas dezenas de reais, confira com lucro ÷ ações.

## Referências

- `references/receitas-sql.md` — consultas prontas por tema: assembleias, FR, insiders, recompra, acionistas,
  DRE/balanço, camadas 1–6 de consistência, série trimestral, FTS; e as regras de resposta (itens 1–12).
- `references/vlmo.md` — insider trading: versões, datas, tipos de movimentação, queries prontas.
- `references/fre.md` — composição acionária (bloco controlador, free float) e remuneração.
- `references/demonstrativos.md` — DRE/balanço/DFC, trimestres com 4T, reapresentações
  (camadas de consistência), notas explicativas.
- `references/manutencao.md` — onboarding de empresa nova, extração de PDFs, atualização
  semanal, montar a base do zero, visualizador local.
