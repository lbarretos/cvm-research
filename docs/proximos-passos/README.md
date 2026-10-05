# Próximos passos: leitura por LLM e padronização dos demonstrativos

Avaliação feita em 2026-09-30 sobre `cvm_research.db` (146 empresas; 12,9 GB + 12,5 GB de WAL).
Cada etapa tem três partes: **avaliação atual** (o que o banco é hoje, medido), **proposta** (o que
fazer) e **stress test** (a proposta testada contra os dados reais, com o veredito e o que o teste
mudou na proposta). Os scripts dos testes estão em [`stress/`](stress/) e rodam só em leitura, ou
sobre uma cópia do banco.

## Etapas, na ordem de execução

A numeração é a ordem recomendada. Cada etapa só depende das anteriores.

| # | Etapa | Camada | Depende de | Veredito do stress test | Esforço |
|---|---|---|---|---|---|
| 1 | [Desempenho e operação](01-desempenho-e-operacao.md) | infraestrutura | — | **Implementada em 2026-10-05, PR #29.** Views idênticas nas 7.174 linhas reais e de 25 s para milissegundos; `VACUUM` ainda pendente | XS–S |
| 2 | [Avaliação contínua](02-avaliacao.md) | transversal | 1 | **Executor implementado em 2026-10-05**; linha de base: 27/28 certas, ~295 mil tokens e US$ 0,45 por pergunta; v1 pendente | S |
| 3 | [MCP, skill e contexto](03-mcp-skill-e-contexto.md) | interface com o LLM | 1, 2 | Parcial: a saída tabular corta 43–46% dos caracteres; o resto só se mede com a Etapa 2 | S–M |
| 4 | [Texto e busca (RAG)](04-texto-e-busca.md) | documentos | 2 | **Aprovada com ajuste**: deduplicação vira requisito (19,7% dos chunks são repetidos) | M |
| 5 | [Versões do template da CVM](05-template-cvm.md) | demonstrativos, L0 | 1 | **Aprovada com ajuste**: a versão é por filing, não por data; bancos precisam de regra própria | S |
| 6 | [Linha econômica por empresa](06-linha-economica.md) | demonstrativos, L1 | 5 | **Aprovada para DRE e BP; insuficiente sozinha na DFC** | S |
| 7 | [Taxonomia canônica](07-taxonomia-canonica.md) | demonstrativos, L2 | 5, 6 | **Viável.** O gabarito da DVA e o modelo apontam erros nas regras que precisam ser corrigidos antes de publicar | M–L |

## Por que esta ordem

1. **Desempenho** primeiro: é pequena, acaba com os timeouts do MCP, e a coluna `versao_template` da Etapa 5
   mora na tabela `filings` que ela cria.
2. **Avaliação** logo em seguida: é a régua. A linha de base tem de ser gravada antes das etapas 3 e 4,
   que mudam o que o LLM vê. A Etapa 1 pode vir antes porque o stress test provou que o resultado das views
   não muda, só a velocidade.
3. **MCP e contexto**: a parte que não depende de nada novo (`resolve_company`, saída tabular, orçamento de
   resposta, timeouts, `CLAUDE.md` → skill). `search_docs`/`read_doc` são ligados ao fim da Etapa 4, e
   `get_financials` ao fim da Etapa 7.
4. **Texto e busca**: é a frente de RAG, independente dos demonstrativos; vem antes deles porque melhora
   todas as perguntas sobre documentos.
5. **Template → 6. Linha econômica → 7. Taxonomia**: uma camada sobre a outra (L0 → L1 → L2).

Quem tiver duas frentes em paralelo pode tocar a Etapa 4 ao mesmo tempo que as etapas 5 a 7: elas não
mexem nas mesmas tabelas. Depois da Etapa 7 vêm as lacunas de dado: ingerir a DMPL e os demonstrativos
individuais.

## Como tocar uma etapa

Uma etapa por conversa e por PR. Para começar:

> Implemente a Etapa N de `docs/proximos-passos/0N-….md`. Use o "Critério de pronto" como aceite, rode de
> novo o stress test da etapa para confirmar e atualize o veredito na tabela acima. Faça num branch e abra um PR.

Ao fechar a etapa, troque o veredito na tabela por "Implementada em AAAA-MM-DD, PR #NN" e registre no
arquivo da etapa o que o stress test refeito mostrou.

## Números centrais

| Medida | Hoje | Com a proposta | Fonte |
|---|---|---|---|
| `vw_balanco`, 1 empresa (banco vivo) | 24,8 s (o MCP aborta em 20 s) | 3 ms | Etapa 1 |
| Mesma view numa cópia compactada, sem WAL | 2,9 s | — | Etapa 1: o WAL/fragmentação custam ~8× |
| Busca: documento certo entre os 5 primeiros | 82,1% | 92,6% | Etapa 4 |
| Caracteres lidos até o trecho (mediana) | 146.970 | 1.937 | Etapa 4 |
| Contas S com código igual e nome diferente que a Camada 5 marcou como estáveis | 5.585 de 5.593 | 0 | Etapa 5 |
| DFC: linhas N casadas ITR 3T → DFP | — | 81% (45,7% pelo código, 35,2% pelo nome) | Etapa 6 |
| D&A DFC × DVA 7.04.01 a menos de 2% | — | 82,2% dos 1.748 DFPs | Etapa 7 |
| Modelo em empresas nunca vistas (F1 vs. regras) | — | 0,918 | Etapa 7 |

## Como reproduzir

O script `stN_…` é o stress test da Etapa N (a Etapa 3 não tem script próprio).

```bash
# Etapa 1. Views (sobre uma CÓPIA com demonstrativos_contabeis, companies e as views)
.venv/bin/python docs/proximos-passos/stress/st1_filings_views.py /caminho/copia.db
# Etapa 2. Conjunto de avaliação
.venv/bin/python docs/proximos-passos/stress/st2_golden.py "$PWD/cvm_research.db" docs/proximos-passos/avaliacao/golden_v0.json
# Etapa 4. Chunks e busca (lê o banco e grava num rascunho)
.venv/bin/python docs/proximos-passos/stress/st4_chunks_fts.py "$PWD/cvm_research.db" /tmp/st4.db 2025
# Etapa 5. Versões de template
.venv/bin/python docs/proximos-passos/stress/st5_template_versao.py "$PWD/cvm_research.db"
# Etapa 6. Linha econômica
.venv/bin/python docs/proximos-passos/stress/st6_linha_economica.py "$PWD/cvm_research.db"
# Etapa 7. Taxonomia (precisa de scikit-learn: venv separada, ver o cabeçalho do script)
/tmp/v/bin/python docs/proximos-passos/stress/st7_taxonomia.py "$PWD/cvm_research.db"
```

Rode da raiz do projeto: os scripts das etapas 5, 6 e 7 importam `scripts/analysis`. No banco vivo, com o
WAL do jeito que está, os testes das etapas 2, 5, 6 e 7 levam de 15 s a 2 min cada.

## Lacunas conhecidas desta avaliação

- As ferramentas MCP novas (Etapa 3) e os embeddings (Etapa 4, item 4.6) não foram prototipados. Os números
  delas aqui são estimativas, não medições.
- Nas etapas 6 e 7, os rótulos das regras funcionam como gabarito aproximado. O F1 do modelo mede a
  concordância com as regras, não a verdade; a verdade externa disponível é a DVA (só para D&A).
- O teste de recuperação da Etapa 4 é sintético (item conhecido, consultas tiradas do próprio texto).
  Ele mede a mecânica da busca, não perguntas reais de analista. As perguntas reais ficam para a Etapa 2.
