# Próximos passos: leitura por LLM e padronização dos demonstrativos

Avaliação feita em 2026-09-30 sobre `cvm_research.db` (146 empresas; 12,9 GB + 12,5 GB de WAL).
Cada etapa tem três partes: **avaliação atual** (o que o banco é hoje, medido), **proposta** (o que
fazer) e **stress test** (a proposta testada contra os dados reais, com o veredito e o que o teste
mudou na proposta). Os scripts dos testes estão em [`stress/`](stress/) e rodam só em leitura, ou
sobre uma cópia do banco.

## Etapas

| # | Etapa | Camada | Veredito do stress test | Esforço |
|---|---|---|---|---|
| 1 | [Desempenho e operação](01-desempenho-e-operacao.md) | infraestrutura | **Aprovada.** Views com resultado idêntico e ~900× mais rápidas | XS–S |
| 2 | [Texto e busca (RAG)](02-texto-e-busca.md) | documentos | **Aprovada com ajuste**: deduplicação vira requisito (19,7% dos chunks são repetidos) | M |
| 3 | [MCP, skill e contexto](03-mcp-skill-e-contexto.md) | interface com o LLM | Parcial: a saída tabular corta 43–46% dos caracteres; o resto só se mede com a etapa 7 | S–M |
| 4 | [Versões do template da CVM](04-template-cvm.md) | demonstrativos, L0 | **Aprovada com ajuste**: a versão é por filing, não por data; bancos precisam de regra própria | S |
| 5 | [Linha econômica por empresa](05-linha-economica.md) | demonstrativos, L1 | **Aprovada para DRE e BP; insuficiente sozinha na DFC** | S |
| 6 | [Taxonomia canônica](06-taxonomia-canonica.md) | demonstrativos, L2 | **Viável.** O gabarito da DVA e o modelo apontam erros nas regras que precisam ser corrigidos antes de publicar | M–L |
| 7 | [Avaliação contínua](07-avaliacao.md) | transversal | Conjunto v0 gerado ([28 perguntas](avaliacao/golden_v0.json)); falta o executor | S |

## Ordem sugerida

```
Semana 1   Etapa 1 (tabela filings, checkpoint, índices)  +  Etapa 7 (executor da linha de base)
Semana 2   Etapa 3 (ferramentas MCP enxutas, CLAUDE.md → skill)  → medir contra a Etapa 7
Semana 2–3 Etapa 4 (plano_cvm + versão por filing; corrigir Camada 5; rodar de novo as Camadas 2, 3 e 5)
Semana 3–5 Etapa 5 (linha_empresa persistida)  →  Etapa 6 (30 primeiros conceitos + get_financials)
Paralelo   Etapa 2 (texto separado, limpeza, dedup, chunks; depois embeddings da camada quente)
Depois     Ingerir DMPL e demonstrativos individuais (lacunas da Etapa 6)
```

A Etapa 7 vem cedo porque é a régua das outras: sem linha de base não há como afirmar que as etapas
2 e 3 melhoraram a resposta do LLM.

## Números centrais

| Medida | Hoje | Com a proposta | Fonte |
|---|---|---|---|
| `vw_balanco`, 1 empresa (banco vivo) | 24,8 s (o MCP aborta em 20 s) | 3 ms | Etapa 1 |
| Mesma view numa cópia compactada, sem WAL | 2,9 s | — | Etapa 1: o WAL/fragmentação custam ~8× |
| Busca: documento certo entre os 5 primeiros | 82,1% | 92,6% | Etapa 2 |
| Caracteres lidos até o trecho (mediana) | 146.970 | 1.937 | Etapa 2 |
| Contas S com código igual e nome diferente que a Camada 5 marcou como estáveis | 5.585 de 5.593 | 0 | Etapa 4 |
| DFC: linhas N casadas ITR 3T → DFP | — | 81% (45,7% pelo código, 35,2% pelo nome) | Etapa 5 |
| D&A DFC × DVA 7.04.01 a menos de 2% | — | 82,2% dos 1.748 DFPs | Etapa 6 |
| Modelo em empresas nunca vistas (F1 vs. regras) | — | 0,918 | Etapa 6 |

## Como reproduzir

```bash
# 1. Views (sobre uma CÓPIA com demonstrativos_contabeis, companies e as views)
.venv/bin/python docs/proximos-passos/stress/st1_filings_views.py /caminho/copia.db
# 2. Chunks e busca (lê o banco e grava num rascunho)
.venv/bin/python docs/proximos-passos/stress/st2_chunks_fts.py "$PWD/cvm_research.db" /tmp/st2.db 2025
# 3. Versões de template
.venv/bin/python docs/proximos-passos/stress/st3_template_versao.py "$PWD/cvm_research.db"
# 4. Linha econômica
.venv/bin/python docs/proximos-passos/stress/st4_linha_economica.py "$PWD/cvm_research.db"
# 5. Taxonomia (precisa de scikit-learn: venv separada, ver o cabeçalho do script)
/tmp/v/bin/python docs/proximos-passos/stress/st5_taxonomia.py "$PWD/cvm_research.db"
# 6. Conjunto de avaliação
.venv/bin/python docs/proximos-passos/stress/st6_golden.py "$PWD/cvm_research.db" docs/proximos-passos/avaliacao/golden_v0.json
```

Rode da raiz do projeto: os scripts 3, 4 e 5 importam `scripts/analysis`. No banco vivo, com o WAL do
jeito que está, os testes 3 a 6 levam de 15 s a 2 min cada.

## Lacunas conhecidas desta avaliação

- As ferramentas MCP novas (Etapa 3) e os embeddings (Etapa 2, R8) não foram prototipados. Os números
  delas aqui são estimativas, não medições.
- Nas etapas 5 e 6, os rótulos das regras funcionam como gabarito aproximado. O F1 do modelo mede a
  concordância com as regras, não a verdade; a verdade externa disponível é a DVA (só para D&A).
- O teste de recuperação da Etapa 2 é sintético (item conhecido, consultas tiradas do próprio texto).
  Ele mede a mecânica da busca, não perguntas reais de analista. As perguntas reais ficam para a Etapa 7.
