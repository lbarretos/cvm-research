# Etapa 3: MCP, skill e contexto

## Avaliação atual

**Ferramentas MCP** (`scripts/mcp/cvm_mcp.py`): `query(sql)`, `list_tables()` e `describe_table()`.
- `query` é a única porta para tudo: o LLM precisa escrever o SQL certo, resolver o CNPJ, saber qual view
  usar, filtrar `dt_ini_exerc` e evitar `LIKE '%…%'` em texto longo.
- A saída é uma lista de dicts, com o nome de cada coluna repetido em cada linha. O teto é de 500 linhas ×
  60 mil chars por célula, **sem limite para a resposta inteira**.
- Segurança bem resolvida: `mode=ro`, authorizer do SQLite e timeout de 20 s em `query`.
- `list_tables` conta as linhas de todas as views e leva ~3 minutos, sem timeout (ver Etapa 1).

**Contexto que o modelo carrega:**

| Fonte | Tamanho | Quando entra |
|---|---|---|
| `CLAUDE.md` do projeto | 55 KB (~14 mil tokens) | **toda** sessão neste diretório |
| `SKILL.md` | 15 KB | quando a skill dispara |
| `references/*.md` da skill | 28 KB | sob demanda |

Mais da metade do `CLAUDE.md` são receitas de SQL e explicações das camadas que a skill também traz.
Numa sessão de pesquisa a informação vem em dobro; numa sessão de desenvolvimento, vem sem necessidade.

## Proposta

| # | Ferramenta nova | Faz | Devolve |
|---|---|---|---|
| 3.1 | `resolve_company(texto)` | ticker, nome parcial ou CNPJ → empresa; avisa quando não está na base | até 5 candidatos |
| 3.2 | `search_docs(consulta, ticker?, categorias?, desde?, ate?, k=10)` | busca por trecho (Etapa 4), já deduplicada e só nas versões mais recentes | trecho + protocolo + data + categoria + link |
| 3.3 | `read_doc(protocolo, chunk?, max_chars=20000)` | lê em volta de um trecho ou por offset | texto + posição |
| 3.4 | `get_financials(ticker, conceitos, fonte, periodos, safra='original')` | lê `fato_padronizado` (Etapa 7), escolhe a view pelo plano de contas e mostra origem e flags | tabela período × conceito |
| 3.5 | `query(sql)` continua | para o que as ferramentas não cobrem | igual |

Regras transversais:
- **Orçamento de resposta**: no máximo 30 mil caracteres por chamada, com aviso de corte.
- **Saída tabular** (`{"colunas": [...], "linhas": [[...]]}`) em vez de dicts.
- Timeout em todas as ferramentas.
- Mover as receitas de SQL do `CLAUDE.md` para `references/` da skill e deixar no `CLAUDE.md` o que serve
  ao desenvolvimento (arquitetura, camadas, manutenção). A skill passa a apontar primeiro para as
  ferramentas 3.1–3.4 e só depois para o SQL livre.

**O que entra agora e o que fica para depois.** Nesta etapa entram a 3.1, a 3.5 e as regras
transversais, que não dependem de nada novo. As outras ficam para quando a base delas existir:
- `search_docs` e `read_doc` (3.2 e 3.3) ao fim da Etapa 4, que cria os trechos;
- `get_financials` (3.4) ao fim da Etapa 7, que cria `fato_padronizado`.

Cada uma delas é medida contra a Etapa 2 quando entrar.

## Stress test

Não há protótipo destas ferramentas ainda. O que foi medido:

| Item | Medida |
|---|---|
| Saída em dicts vs. tabular (JSON) | `vw_dre` da WEGE3, 8 linhas × 13 colunas: 3.131 → 1.679 chars (**−46%**). DFC do DFP em `demonstrativos_contabeis`, 500 linhas × 5 colunas: 78.640 → 44.733 chars (**−43%**) |
| `CLAUDE.md` → skill | ~10 mil tokens a menos por sessão neste diretório (medido pelo tamanho do arquivo) |
| `get_financials` | Depende da Etapa 7; as views da Etapa 1 já respondem em 3 ms, então a latência não é problema |
| `search_docs` | Os números são os da Etapa 4 (1.937 chars lidos contra 146.970) |

**Veredito: só o formato de saída foi testado (−43% a −46% de caracteres, com o mesmo conteúdo).** O ganho real só aparece na Etapa 2, comparando a mesma bateria de
perguntas antes e depois (acerto, chamadas por pergunta, tokens e SQL com erro). É por isso que a Etapa 2
roda **antes** desta.

**Riscos a observar:**
- Ferramentas demais confundem o modelo. Cinco é o teto razoável.
- `get_financials` esconde a origem do número. Ele precisa devolver `origem`, `flag`, `metodo` e
  `confianca` junto com o valor, senão a regra 12 do `CLAUDE.md` (sempre mostrar a flag) se perde.

## Critério de pronto

- Na Etapa 2: acerto igual ou maior, 30% menos tokens por pergunta e zero consultas abortadas por timeout.

## Resultado (2026-10-06)

Entrou: `resolve_company`, saída tabular, orçamento de 30 mil caracteres por resposta (célula de até 25 mil),
timeout em todas as ferramentas, a skill versionada em [`skills/cvm-research/`](../../skills/cvm-research/)
(com `references/receitas-sql.md` vinda do `CLAUDE.md`, que caiu de 56 para 39 KB) e a regra da D&A na skill.
`search_docs`/`read_doc` e `get_financials` seguem para as etapas 4 e 7.

Etapa 2 sobre o mesmo v0 (`avaliacao/runs/`):

| Medida | Antes | Depois |
|---|---|---|
| Acerto | 27/28 | **28/28** (a q011, D&A da CSAN3, passou com a regra na skill) |
| Consultas abortadas por timeout | 0 | 0 |
| Erros de ferramenta | 5 | **0** |
| Turnos por pergunta | 4,6 | 6,1 |
| Chamadas de ferramenta | 3,5 | 4,4 |
| Tokens por pergunta | 294 mil | 305 mil (+4%) |
| Custo da execução | US$ 12,59 | US$ 12,49 |

**Veredito: critério de pronto cumprido pela metade.** Acerto igual ou maior e zero abortadas: sim. **30% menos
tokens: não.** Quase todos os ~300 mil tokens são o prefixo fixo da sessão (ferramentas, plugins e skills do
usuário, ~60 mil por turno) relido a cada turno. O que as ferramentas economizam (tabular, orçamento, 4 mil tokens do
`CLAUDE.md`) é pouco perto disso, e a skill nova fez a sessão dar **mais turnos** (+1,5), o que custa mais que o
ganho. A alavanca de tokens é cortar turnos, não bytes: a próxima iteração é fazer a skill mandar `resolve_company` e a
consulta de dados em paralelo, ou mandar a consulta direto pelo ticker nas views, e voltar a medir. A meta de 30% foi
posta antes de se saber que o prefixo domina; revê-la para "turnos por pergunta" é mais honesto.
