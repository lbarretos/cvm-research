# Etapa 2: Avaliação contínua

## Avaliação atual

Não existe medida de qualidade das respostas do LLM. A suíte `pytest` valida o banco e as camadas, mas não
se o Claude, pela skill e pelo MCP, chega ao número certo, com quantas chamadas e com quantos tokens.
Sem essa medida, não há como provar que as etapas 1, 3, 4 e 7 melhoraram alguma coisa.

## Proposta

1. **Conjunto de perguntas com resposta conhecida** (`avaliacao/golden_vN.json`), gerado do próprio banco
   e revisado à mão. Cada pergunta traz a resposta, a tolerância, a consulta de referência e **a armadilha
   que ela testa**.
2. **Executor**: roda cada pergunta numa sessão nova do Claude com a skill e o MCP (Claude Agent SDK ou
   `claude -p`) e grava a resposta, as chamadas de ferramenta, os tokens, o tempo e os erros de SQL.
   A correção é automática para números (tolerância relativa) e contagens, e feita por outro modelo, com
   critério escrito, para as perguntas de documento.
3. **Métricas**: acerto por tipo, chamadas por pergunta, tokens por pergunta, consultas abortadas e SQL
   com erro.
4. **Quando rodar**: antes e depois de cada etapa, e a cada mudança na skill, no `CLAUDE.md` ou no MCP.
5. **Crescimento**: v0 com 28 perguntas, v1 com ~80. A v1 inclui perguntas de padronização ("capex de X
   em 2023"), de texto conceitual ("a empresa sinalizou corte de dividendos?") e de documentos longos
   ("o que a proposta da AGO de 2025 diz sobre remuneração?").

## O que já existe

Script: [`stress/st2_golden.py`](stress/st2_golden.py), que gera [`avaliacao/golden_v0.json`](avaliacao/golden_v0.json)
com 28 perguntas:

| Tipo | n | Armadilha testada |
|---|---|---|
| número (DFP) | 8 | resolver o ticker; usar o DFP, não somar ITRs |
| número (4T isolado) | 2 | o 4T não existe no ITR: tem de vir de `demonstrativos_trimestrais`, safra original |
| número (D&A) | 2 | D&A está na DVA 7.04.01, não numa conta fixa da DFC |
| número (banco) | 2 | `vw_dre` volta NULL para banco; o certo é `vw_dre_financeiro` |
| contagem de FR | 4 | filtrar por `data_entrega` |
| último FR + tema | 4 | ordenar por data de entrega e ler o texto |
| maior acionista | 3 | não misturar os níveis da cadeia de controle |
| reapresentação | 2 | dar o original e o reapresentado lado a lado |
| sem dado | 1 | a defasagem do IPE: dizer até quando vai a base, não "não houve" |

## Stress test do próprio conjunto

O conjunto foi conferido antes de servir de régua:
- As 28 respostas existem e não são nulas (o gerador falha se alguma vier vazia).
- **Dependência do tempo**: as perguntas de "último FR" e as contagens mudam com o job semanal, e números
  reapresentados mudam numa recarga. Por isso o arquivo grava `gerado_em`, e o executor tem de comparar
  contra o banco do mesmo dia ou congelar as respostas.
- **Ambiguidade**: a contagem de FR inclui reapresentações. Um humano poderia contar só os originais. A
  armadilha está escrita na pergunta, e a correção deve aceitar as duas contagens.
- **Viés**: as empresas foram sorteadas com semente fixa só no plano padrão, mais 2 bancos. Faltam
  seguradoras e exercício fora do calendário; entram na v1.

**Veredito:** o conjunto v0 serviu de linha de base. O executor foi implementado.

## Executor (implementado em 2026-10-05)

[`scripts/eval/run_eval.py`](../../scripts/eval/run_eval.py): uma sessão nova de `claude -p` por pergunta,
na raiz do projeto (carrega o `CLAUDE.md`), só com o MCP `cvm-research` (`--strict-mcp-config`, ferramentas
`query`/`list_tables`/`describe_table`), em 4 sessões paralelas. Grava em `avaliacao/runs/AAAA-MM-DD_rotulo.json`
a resposta, chamadas de ferramenta, erros, consultas abortadas, tokens, custo e tempo.

```bash
.venv/bin/python scripts/eval/run_eval.py --rotulo minha-mudanca     # v0 inteiro
.venv/bin/python scripts/eval/run_eval.py --ids q011,q028 --rotulo x # só algumas
.venv/bin/python scripts/eval/run_eval.py --comparar runs/a.json runs/b.json
```

- Número, contagem e par original/reapresentado: correção automática por uma linha final `RESPOSTA:`, que o
  executor pede no prompt. Contagem aceita também o total sem as reapresentações (até 3 a menos), desde que a
  resposta cite a reapresentação.
- Documento, fato e sem dado: um segundo `claude -p` sem ferramentas julga contra a referência e a armadilha.
  O juiz é estrito: no teste, reprovou uma resposta correta no corpo cujo título citava um fato com data de
  ontem. Vale ler `nota_correcao` dos erros antes de concluir que algo regrediu.
- Custo: cada execução do v0 gasta cerca de US$ 12,6 (a skill e o `CLAUDE.md` pesam ~295 mil tokens por pergunta,
  quase tudo cache). Isso é, por si, a métrica que a Etapa 3 quer baixar.

### Linha de base (2026-10-05, antes das etapas 3 e 4)

| Medida | Valor |
|---|---|
| Acerto geral | 27 de 28 (96,4%) |
| Chamadas de ferramenta por pergunta | 3,54 |
| Tokens por pergunta | ~295 mil |
| Erros de ferramenta / consultas abortadas | 5 / 0 |
| Duração média por pergunta | 15 s |
| Custo da execução | US$ 12,59 |

O único erro é a **q011** (D&A da CSAN3): o modelo usou a linha de impairment da DFC e deu R$ 3,87 bi; o certo é a
DVA 7.04.01, R$ 7,02 bi. O modelo percebeu a diferença, explicou-a, e mesmo assim escolheu o número errado:
a regra "D&A está na DVA" não está clara o bastante no `CLAUDE.md`. Fica para a Etapa 3 (skill).

O v0 não tem folga para medir melhora em acerto (96%). Quem mostra ganho na Etapa 3 são tokens, chamadas e
custo; as perguntas difíceis (texto conceitual, documentos longos, padronização) entram na v1.

## Critério de pronto

- ✅ Executor rodando o v0 em menos de 30 minutos (a execução levou ~3 min) e gravando um relatório comparável entre execuções (`--comparar`).
- ✅ Linha de base registrada **antes** de qualquer mudança das etapas 3 e 4: `avaliacao/runs/2026-10-05_baseline-pre-etapa3.json`.
- Pendente: a v1 (~80 perguntas).
