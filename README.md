# CVM Research

**Uma base local dos documentos e demonstrativos de empresas abertas brasileiras, que o Claude consulta conversando.**

Baixar os dados da CVM é a parte fácil. O problema é que eles não são comparáveis ao longo do tempo: a
empresa renumera as contas que cria a cada trimestre, o DFP usa um layout diferente do ITR, o mesmo período
aparece em cinco documentos com valores diferentes, e a DFC só existe acumulada no ano. Quem monta série
histórica somando código com código soma linhas trocadas e não percebe.

Este repositório baixa, **trata** e deixa o resultado auditável. Cada valor trimestral registra de qual linha
de qual documento ele saiu. Toda reapresentação fica marcada, com o valor original e o reapresentado lado a
lado. O que o casamento não conseguiu resolver com confiança vira fila de revisão em vez de número inventado.

SQLite local, um arquivo, sem servidor e sem nuvem. Você escolhe as empresas e o período.

**Para quem:** analista de ações que monta modelo à mão e cansou de conferir número por número no PDF;
pesquisador que precisa de série histórica confiável da CVM; quem quer conversar com dados de empresa
aberta em vez de garimpar o portal.

---

## Quick start

1. Instale (30 segundos, abaixo)
2. Monte uma base enxuta: `bash bootstrap.sh --universo ibov --desde 2022 --sem-pdf` (~20 min)
3. Pergunte ao Claude: *"Compare a margem EBIT de WEGE3 e EMBR3 desde 2022"*
4. Pergunte: *"O lucro do 4T24 da Localiza foi reapresentado depois?"*
5. Pergunte: *"Mostre o fluxo de caixa de financiamento da Multiplan trimestre a trimestre, e de onde veio cada número"*

Pare aí. Você já vai saber se serve.

---

## Instalação — 30 segundos

**Requisitos:** macOS 11+, Python 3.10+, [Claude Code](https://docs.anthropic.com/en/docs/claude-code).
SQLite já vem no macOS. Não precisa de Node, Docker nem conta em lugar nenhum.

### Passo 1 — instalar

Abra o Claude Code e cole isto. Ele faz o resto.

> Instale o CVM Research: rode
> **`git clone https://github.com/lbarretos/cvm-research.git ~/cvm-research && cd ~/cvm-research && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && bash setup.sh && echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env && claude mcp add cvm-research -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"`**
> e confirme com `claude mcp list` que aparece `cvm-research: ✓ Connected`. Depois leia o CLAUDE.md do
> repositório e me pergunte quais empresas e a partir de que ano eu quero na base antes de montar.

> ⚠️ Não coloque o projeto em pasta sincronizada (OneDrive, iCloud, Dropbox). O banco fica grande e muda
> toda semana; sincronizar é lento e pode corromper o arquivo.

### Passo 2 — montar a base

Em português mesmo, dentro do Claude Code:

> *"Monte a base com o universo IBOV, documentos de 2022 para cá, sem extrair PDF por enquanto."*

O [CLAUDE.md](CLAUDE.md) ensina o Claude a traduzir isso no comando, mostrar o plano antes e acompanhar.
No terminal é a mesma coisa:

```bash
bash bootstrap.sh --universo ibov --desde 2022 --sem-pdf
```

A instalação leva 30 segundos. A base leva mais: veja os tempos em [O pipeline](#o-pipeline).

---

## Veja funcionando

```
Você:   O 2T26 da Multiplan tem R$ 347 mi de pagamento de encargos sobre
        debêntures. Quanto foi só o trimestre?

Claude: [consulta demonstrativos_trimestrais]
        −202,1 mi no 2T isolado.

        O acumulado do semestre é −347,0 e o do 1T é −144,9. Mas repare:
        no 1T essa linha estava no código 6.03.06 com o nome "Pagamento
        de encargos e debêntures"; no 2T ela está em 6.03.08 como
        "Pagamento de encargos sobre debêntures".

        O 6.03.08 do 1T era outra coisa: dividendos, −97,5 mi.
        Subtrair por código daria −249,5 e estaria errado.

Você:   Como você sabe que casou a linha certa?

Claude: A tabela grava isso. Esta linha tem cd_conta_b = 6.03.06 e
        casamento = 'reformulacao'. Os nomes batem com 0,94 de
        similaridade. Confere contra o filing:

        ITR 1T26  6.03.06  Pagamento de encargos e debêntures   −144,9
        ITR 2T26  6.03.08  Pagamento de encargos sobre debênt.  −347,0

Você:   E a série fecha?

Claude: Fecha. Somei os quatro trimestres de cada linha de 2021 a 2025 e
        comparei com o acumulado do DFP: 30 de 30 batem ao centavo.
```

O número que interessa não é o que está no PDF. É o que sobrou depois de acertar qual linha é qual.

---

## O pipeline

Quatro etapas, nesta ordem. O `bootstrap.sh` roda as três primeiras.

**Baixa → Trata → Verifica → Pesquisa**

| Etapa | O que roda | Tempo (IBOV, ~78 empresas) |
|---|---|---|
| **Baixa** | sete ingestores puxam os ZIPs da CVM | 20–40 min |
| **Trata** | cinco camadas de consistência cruzam os documentos | ~4 min |
| **Verifica** | `pytest` relê o banco e recalcula o tratamento do zero | segundos |
| **Pesquisa** | você conversa; o Claude consulta pelo MCP | — |

A etapa de texto dos PDFs é separada porque é longa (6–12 h no IBOV) e opcional para quem só quer os
números. `--sem-pdf` adia, `--so-pdf` retoma. Sem ela você tem tudo dos demonstrativos, mas não tem busca
full-text nem leitura de fatos relevantes.

**A etapa "Trata" é o que distingue este repositório de um downloader.** Sem ela o banco tem os dados
brutos e nada mais. São cinco camadas, cada uma resolvendo um jeito diferente de o dado enganar:

| Camada | Pergunta que responde | Onde grava |
|---|---|---|
| 1 | A soma fecha dentro do próprio documento? | `consistency_flags` |
| 2 | Este período foi reapresentado depois? Quanto mudou? | `consistency_flags` |
| 3 | Esta conta sumiu, ou só mudou de lugar? | `consistency_flags` |
| 5 | Por onde esta linha passou ao longo dos anos? | `cd_conta_ds_timeline` |
| 6 | Quanto foi só este trimestre, e de qual linha saiu? | `demonstrativos_trimestrais` |

Nenhuma delas altera o valor publicado pela CVM. Tudo é metadado ao lado do original, para você decidir.
Detalhe de cada uma em [CLAUDE.md](CLAUDE.md); o desenho em `docs/superpowers/plans/`.

---

## O que dá para perguntar

**Eventos e documentos**
- *"Fatos relevantes da Embraer no último ano, classificados por tipo de impacto"*
- *"Resumo das últimas AGOs e AGEs da WEG, com o que foi deliberado"*
- *"Procure 'arbitragem' nos documentos da Braskem desde 2023"*

**Números**
- *"Compare a margem EBIT de WEGE3 e EMBR3 de 2016 a 2024"*
- *"Fluxo de caixa operacional trimestral da Vale nos últimos 8 trimestres"*
- *"Qual foi o 4T da receita da Suzano em cada ano desde 2020?"*

**Qualidade do dado**
- *"O EBITDA de 2022 da Natura mudou entre o DFP original e o seguinte?"*
- *"Quais contas da DFC da Equatorial foram renumeradas nos últimos 5 anos?"*
- *"Tem algum número trimestral da Cosan que o sistema não conseguiu calcular com confiança?"*

**Insiders e capital**
- *"Houve compra por insiders da Localiza perto de algum resultado em 2024?"*
- *"Quais programas de recompra estão vigentes?"*
- *"Quem são os maiores acionistas da Vale hoje?"*

---

## Cobertura e período

Você escolhe na carga, e pode mudar depois.

**Cobertura** (`--universo`): `ibov` é o ponto de partida recomendado, com cerca de 78 empresas. Também
aceita `ibrx`, `todas` (as ~443 ativas da B3) ou **um arquivo com a sua lista de tickers**, que costuma ser
a melhor opção quando você já sabe o que acompanha:

```
ticker,empresa
PETR4,Petrobras
VALE3,Vale
WEGE3,WEG
```

CSV com coluna `ticker`, as outras colunas ignoradas, ou um ticker por linha. Ticker fora do catálogo da B3
é avisado e pulado. O universo é **aditivo**: soma ao `watchlist.csv` e nunca remove. Para começar limpo,
`--substituir`, que faz backup antes.

**Período** (`--desde ANO`): vale para todas as fontes. Cada uma tem um primeiro ano possível (IPE 2015,
VLMO 2018, ITR 2011, DFP e FRE 2010) e pedir antes disso sobe para o piso com aviso, em vez de baixar vazio.

```bash
bash bootstrap.sh --universo ibov --desde 2020            # IBOV, de 2020 para cá
bash bootstrap.sh --universo minhas-empresas.csv          # sua lista, série completa
bash bootstrap.sh --universo todas --sem-pdf              # cobertura máxima, sem texto
bash bootstrap.sh --dry-run                               # mostra o plano sem baixar nada
```

`bash bootstrap.sh --help` lista tudo. Passo a passo e solução de problemas em [INSTALL.md](INSTALL.md).

---

## Manutenção

A CVM atualiza os ZIPs do IPE **toda segunda entre 8h e 8h30**. Documento mais recente que isso só no
portal RAD (`rad.cvm.gov.br`).

```bash
bash scripts/update_weekly.sh                       # ingestores + consistência + PDFs
bash scripts/install_weekly_launchd.sh              # agenda para toda segunda, 9h
bash scripts/install_weekly_launchd.sh --status     # estado + último log
```

O job semanal cobre o ano corrente e o anterior. Para refazer o histórico ou mudar a cobertura, rode o
`bootstrap.sh` de novo. Logs em `logs/update_*.log`, os 12 mais recentes.

Confira o tratamento a qualquer momento:

```bash
.venv/bin/python -m pytest tests/ -q
```

A suíte inclui testes que releem o banco e recalculam o tratamento a partir do dado bruto: conferem que
cada valor trimestral é mesmo a subtração de duas linhas equivalentes. Eles pulam sozinhos se o banco não
existir ou se a sua cobertura não tem as empresas da amostra.

---

## Referência

| Arquivo | Para quê |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Schema, queries prontas e como o Claude deve pesquisar. É o arquivo mais importante do repositório. |
| [INSTALL.md](INSTALL.md) | Instalação detalhada, MCP no Claude Code e no app, troubleshooting |
| [TODOS.md](TODOS.md) | Backlog |
| `docs/superpowers/plans/` | Desenho de cada camada de consistência, com as medições |

### Fontes

| Script | Fonte na CVM | Tabelas |
|---|---|---|
| `ingest_ipe.py` | IPE (ZIPs anuais) | `ipe_docs` |
| `extract_pdf.py` | PDFs dos documentos | `ipe_docs.texto_extraido`, `ipe_docs_fts` |
| `ingest_dfp.py` / `ingest_itr.py` | DFP e ITR | `demonstrativos_contabeis` |
| `ingest_vlmo.py` | VLMO | `vlmo_posicao`, `vlmo_movimentacoes` |
| `ingest_fre.py` | FRE | `fre_capital_social`, `fre_posicao_acionaria`, `fre_remuneracao_orgao` |
| `ingest_recompra.py` | Recompra | `recompra_programas` |
| `ingest_notas_explicativas.py` | Pacote do filing (rad.cvm.gov.br) | `notas_explicativas` (sob demanda) |
| `scripts/analysis/run_all.py` | — (cruza o que já está no banco) | `consistency_flags`, `cd_conta_ds_timeline`, `demonstrativos_trimestrais` |

Estrutura completa das pastas e dos scripts: [INSTALL.md](INSTALL.md).

### Um limite que vale saber

A CVM não arquiva versões anteriores dos documentos: cada base guarda a versão que estava no ZIP no dia do
download. Duas instalações montadas em datas diferentes divergem nos períodos reapresentados no intervalo.
O repositório reproduz o método com fidelidade total, e o dado com a fidelidade que a fonte permite. Ao
comparar números com outra máquina, cite a data da carga.

---

## Histórico

O projeto começou em Supabase/PostgreSQL e migrou para SQLite local em junho de 2026 (um arquivo, zero
serviços). O MCP passou de `mcp-server-sqlite` (npx) para um servidor Python próprio em setembro de 2026.
Os workflows de GitHub Actions foram removidos: toda a ingestão roda localmente.

**18/09/2026 — casamento de linhas no desacúmulo (Camada 6).** A Camada 6 subtraía acumulados casando as
linhas por `cd_conta`, que não é estável entre filings. Resultado: 21% das linhas derivadas da DFC no 2T e
no 3T e 39% no 4T subtraíam uma linha de outra, quase sempre sem flag — cerca de 24,6 mil valores errados
só na DFC de 2T e 3T, em todas as empresas. Passou a usar a escada de casamento da Camada 5 e a gravar o
par em `cd_conta_b`/`casamento`. Pares de similaridade ambígua viram fila de revisão em vez de número.

Duas variantes do mesmo erro apareceram na validação. A CVM re-letrou o plano dos bancos entre o ITR do
3T/2017 e o DFP/2017, então confiar no código fixo da CVM também erra. E a similaridade textual não
distingue sentido contábil: "Captação" e "Pagamento de debêntures" pontuam 0,756, e havia 586 pares casados
com o sentido invertido. Depois da correção: zero inversões e zero erros de aritmética em 1,23 milhão de
valores conferidos contra o dado bruto.
