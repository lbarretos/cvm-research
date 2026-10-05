# Etapa 4: Texto e busca (RAG)

## Avaliação atual

**Volume.** 163.178 documentos com texto somam 6,70 bi de caracteres (~1,9 bi de tokens). Dois terços dos
documentos têm menos de 10 mil caracteres, mas respondem por só 6% do volume. Os 8.815 documentos acima de
200 mil caracteres respondem por 60% dele.

| Categoria | Docs | Caracteres | Observação |
|---|---|---|---|
| Dados Econômico-Financeiros | 19.872 | 2,59 bi (39%) | DFs completas, press-releases, DFs em inglês (0,74 bi) |
| Assembleia | 23.773 | 1,71 bi | propostas e manuais longos |
| Documentos de Oferta | 1.914 | 0,63 bi | prospectos |
| Comunicado ao Mercado | 35.625 | 0,39 bi | |
| VLMO (art. 11) | 29.021 | 0,11 bi | já estruturado em `vlmo_movimentacoes` |
| Fato Relevante | 11.011 | 0,07 bi | |

**Mecânica da busca hoje:**
- A unidade do FTS é o documento inteiro, que chega a 12 milhões de caracteres. O `bm25` perde o
  sentido nesses documentos, e depois de achar o documento o LLM lê às cegas com `substr(…, 20000)`.
- O tokenizer é o `unicode61`: acentos funcionam (`aquisição` = `aquisicao` = 38.372 docs), mas não há
  radicalização (`aquisições` dá 17.870 e `aquisi*` dá 41.124). A skill não ensina o prefixo.
- `protocolo_entrega` e `cnpj_companhia` estão indexados como texto no FTS. `categoria`, `tipo` e
  `data_entrega` não estão, então todo filtro exige join.
- Não há busca semântica.

**Ruído:**

| Fonte | Tamanho |
|---|---|
| Versões substituídas (mesma chave empresa/categoria/tipo/espécie/data/assunto) | 8.676 docs |
| Reapresentações (`RE`/`RC`) | 17.496 docs |
| Hifenização no fim da linha | ~31% dos docs (amostra de 410) |
| Sobras de `(cid:N)` Identity-H | ~4% dos docs (amostra) |
| Falhas de extração (em geral digitalizados) | 5.719 docs |

## Proposta

| # | Ação |
|---|---|
| 4.1 | Separar o texto: `ipe_texto(protocolo_entrega PK, texto)`. `ipe_docs` fica com os metadados (~100 MB) |
| 4.2 | Limpeza antes de dividir em trechos: juntar a hifenização (`(\w)-\n(\w)`), remover linhas curtas que se repetem 3+ vezes no documento (cabeçalho e rodapé) e colapsar espaços |
| 4.3 | **Deduplicação** (entrou por causa do stress test): `hash` do trecho normalizado. Trecho repetido de outro documento da mesma empresa é gravado uma vez, com a lista de protocolos em que aparece |
| 4.4 | `ipe_chunks(chunk_id, protocolo, ordem, texto)` com ~2 mil caracteres, corte em parágrafo e sobreposição de 200. Metadados desnormalizados (cnpj, ticker, categoria, tipo, espécie, data_entrega, `is_latest`). FTS5 sobre os trechos, com os metadados como colunas `UNINDEXED` |
| 4.5 | Curadoria em camadas. **Quente**: FR, CM, AVI, RCA, Assembleia (ata, proposta, sumário, edital) e press-release. **Fria**: DFs completas, relatórios de agente fiduciário, escrituras e prospectos (FTS, sem embedding). **Fora do índice**: VLMO em PDF e DFs em inglês |
| 4.6 | Busca híbrida só na camada quente: embeddings em `sqlite-vec`, fundidos ao BM25 por RRF (reciprocal rank fusion) |
| 4.7 | `is_latest_version`/`substituido_por` em `ipe_docs`. A busca devolve a versão mais recente por padrão |

## Stress test

Script: [`stress/st4_chunks_fts.py`](stress/st4_chunks_fts.py). Copia a camada quente de 2025 (10.101
documentos, 310 mi de caracteres) para um banco de rascunho, aplica 4.2 e 4.4 e compara o FTS por
documento (hoje) com o FTS por trecho.

**Teste de item conhecido.** Para 391 trechos sorteados, a consulta tem 4 termos raros do próprio trecho,
sem filtro de empresa. O teste mede se o documento de origem volta e quanto o LLM leria até o trecho
(hoje, o documento inteiro; com a proposta, a soma dos trechos até o acerto).

| Unidade | hit@1 | hit@5 | Chars lidos até o trecho (p50) | p90 | Latência p50 |
|---|---|---|---|---|---|
| Documento (hoje) | 46,3% | 82,1% | 146.970 | 767.219 | 0,2 ms |
| **Trecho** | **57,3%** | **92,6%** | **1.937** | **5.928** | 0,2 ms |

**Limpeza e trechos:**
- 22.878 hifenizações juntadas e 92.322 linhas distintas de cabeçalho/rodapé removidas;
- 187.884 trechos (18,6 por documento; p50 de 1.814 chars, p95 de 2.127);
- construção em 26 s e FTS em 9 s (o rascunho ocupa 980 MB).

**O achado que mudou a proposta: 19,7% dos trechos são duplicados exatos.**

| Origem da duplicata | Trechos |
|---|---|
| Outro documento **da mesma empresa** (republicação, FR + CM com o mesmo texto, versão nova) | 35.980 (97%) |
| Mesmo documento | 676 |
| Empresas diferentes (texto-padrão) | 299 |

Parte do hit@1 de 57% não é erro: é empate com a cópia do mesmo texto em outro documento da mesma
empresa. Sem a deduplicação (4.3), os 10 resultados de uma busca trariam o mesmo parágrafo várias vezes e
gastariam o orçamento de contexto do LLM. Por isso a 4.3 passou a ser requisito.

**Hifenização:** nas 60 palavras que mais quebram no fim da linha, juntar as partes acrescentou 988
documentos encontrados (+1,0%). O ganho é real, mas pequeno. Fica na etapa por ser barato, não por ser
decisivo.

**Projeção para a base inteira:** 6,7 bi de chars dão ~3,6 mi de trechos. Só a camada quente, com
deduplicação, fica perto de 1 mi. Com 768 dimensões em int8, os embeddings da camada quente ocupam
~0,8 GB (estimativa, não medida).

**Veredito: aprovada com ajuste** (a deduplicação vira requisito). O ganho de hit@5 (+10,5 p.p.) é
moderado; o ganho grande está no custo, que cai 76× em caracteres lidos por resposta.

**Limites do teste:**
- É sintético, com consultas tiradas do próprio texto; não mede perguntas conceituais, que são justamente o
  alvo dos embeddings (4.6).
- As consultas vêm do texto limpo, o que favorece um pouco os trechos (o efeito da hifenização é de ~1%).
- A busca semântica não foi prototipada.

## Critério de pronto

- Na Etapa 2, as perguntas do tipo "documento" são respondidas com menos de 10 mil chars de texto
  lido por pergunta.
- Nenhum resultado repete um trecho idêntico dentro do top-10.
- Busca por trecho com p95 abaixo de 50 ms na base inteira.
