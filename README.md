# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras, organizada para pesquisa via Claude.

**Fontes:** IPE · VLMO · Recompra · FRE · DFP/ITR · Notas Explicativas (sob demanda)  
**Cobertura:** 145 empresas (IBOV + cobertura própria) · IPE desde 2015 · demonstrativos desde 2010  
**Banco:** SQLite local (`cvm_research.db`) — sem servidor, sem Docker, sem cloud  
**Tamanho:** ~12 GB (mais da metade é texto extraído dos PDFs + índice full-text) · ~4,9M linhas  
**Atualização:** `bash scripts/update_weekly.sh` (manual) ou job launchd toda segunda 9h

> **Instalação passo a passo, MCP e troubleshooting:** [INSTALL.md](INSTALL.md)  
> **Schema, queries e comportamento do Claude:** [CLAUDE.md](CLAUDE.md)  
> **Backlog:** [TODOS.md](TODOS.md)

---

## Pré-requisitos

| Ferramenta | Versão mínima | Verificar |
|---|---|---|
| macOS | 11+ (Big Sur) | `sw_vers -productVersion` |
| Python | 3.10+ | `python3 --version` |
| Claude Code CLI | qualquer | `claude --version` |
| Claude desktop app | qualquer | (opcional, para chat visual) |

SQLite vem instalado no macOS. Não é preciso Node.js: o MCP é um script Python do próprio projeto.

> ⚠️ **Não coloque o projeto em pasta sincronizada (OneDrive, iCloud, Dropbox).** O banco tem ~12 GB e muda toda semana; sincronizar isso é lento e pode corromper o arquivo. Se ficar em `~/Documents`, `~/Desktop` ou `~/Downloads`, o job automático do launchd precisa de Acesso Total ao Disco (ver [INSTALL.md](INSTALL.md#troubleshooting)).

---

## Setup rápido

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash setup.sh                                          # cria cvm_research.db vazio
echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env
claude mcp add cvm-research -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"
```

Carga inicial (30–60 min, baixa ~15 GB de ZIPs da CVM):

```bash
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_companies.py
python ingest_ipe.py --desde 2015
python ingest_vlmo.py --desde 2018
python ingest_recompra.py
python ingest_fre.py --desde 2010
python ingest_dfp.py --historico --desde 2010
python ingest_itr.py --desde 2011
python extract_pdf.py            # texto dos PDFs (opcional, demorado; pode rodar em lotes com --limite)
```

Verifique com `claude mcp list` (deve mostrar `cvm-research: ✓ Connected`) e pergunte ao Claude *"Quantas linhas tem a tabela ipe_docs?"*.

O [INSTALL.md](INSTALL.md) cobre também a opção de copiar um banco já populado de outra máquina e o setup no Claude desktop app.

---

## Atualização da base

> **Cadência da CVM:** os ZIPs do IPE são atualizados **toda segunda-feira entre 8h00 e 8h30**. Para documentos mais recentes que isso, consulte o portal RAD: `rad.cvm.gov.br`.

```bash
bash scripts/update_weekly.sh                                   # tudo de uma vez (ingestores + extract_pdf)
EXTRACT_LIMIT=2000 RETRY_FAILED=1 bash scripts/update_weekly.sh # com re-tentativa de PDFs falhos
```

Automático (launchd, segunda 09:00):

```bash
bash scripts/install_weekly_launchd.sh            # agenda
bash scripts/install_weekly_launchd.sh --run-now  # agenda e roda agora
bash scripts/install_weekly_launchd.sh --status   # estado + último log
bash scripts/install_weekly_launchd.sh --uninstall
```

Logs em `logs/update_*.log` (mantidos os 12 mais recentes). Se o Mac estiver dormindo no horário, o launchd executa ao acordar. Dia e hora: `WEEKDAY=1 HOUR=9 MINUTE=0`.

Passo a passo, se preferir:

```bash
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_ipe.py && python ingest_vlmo.py && python ingest_recompra.py
python ingest_fre.py && python ingest_dfp.py && python ingest_itr.py
python extract_pdf.py --limite 1000
```

Notas explicativas (texto completo do ITR/DFP) não entram no fluxo semanal: cada PDF tem dezenas de MB. Ingira sob demanda:

```bash
python ingest_notas_explicativas.py --cnpj <CNPJ> --ano 2026 --fonte ITR
```

---

## Uso com o Claude

Com o MCP conectado, basta conversar. O Claude consulta o banco quando necessário.

- *"Resumo das últimas AGOs e AGEs da WEG com o que foi deliberado"*
- *"Fatos relevantes da Embraer no último ano — classifica por tipo de impacto"*
- *"Houve compra de ações por insiders da Localiza próximo a algum resultado em 2024?"*
- *"Compare a margem EBIT de WEGE3 e EMBR3 de 2016 a 2024"*
- *"Quais programas de recompra estão vigentes?"*
- *"Quem são os maiores acionistas da Vale hoje?"*

---

## Estrutura do projeto

```
cvm-research/
├── README.md                       # este arquivo
├── INSTALL.md                      # instalação, MCP (Code e desktop), troubleshooting
├── CLAUDE.md                       # schema, queries e instruções para o Claude
├── TODOS.md                        # backlog
├── watchlist.csv                   # 145 empresas com CNPJ, ticker e código CVM
├── schema.sql                      # schema SQLite completo (tabelas + views + FTS5)
├── setup.sh                        # cria cvm_research.db a partir de schema.sql
├── requirements.txt                # dependências Python (inclui mcp)
├── .env.example                    # template do .env (DATABASE_URL)
├── scripts/
│   ├── update_weekly.sh            # roda todos os ingestores + consistência + extract_pdf (lock + log)
│   ├── install_weekly_launchd.sh   # agenda update_weekly.sh no launchd (segunda 9h)
│   ├── mcp/cvm_mcp.py              # servidor MCP (stdio, somente leitura)
│   ├── ingest/
│       ├── utils.py                # conexão SQLite + helpers de download/conversão
│       ├── catalog.py              # baixa catálogo B3+CVM → company_catalog.csv
│       ├── add_companies.py        # adiciona empresas do catálogo à watchlist
│       ├── ingest_companies.py     # sincroniza watchlist.csv → tabela companies
│       ├── ingest_ipe.py           # documentos CVM (metadados) — flag: --desde ANO
│       ├── ingest_vlmo.py          # insider trading
│       ├── ingest_recompra.py      # programas de recompra
│       ├── ingest_fre.py           # capital, acionistas, remuneração
│       ├── ingest_dfp.py           # demonstrativos anuais — flags: --historico, --desde ANO
│       ├── ingest_itr.py           # demonstrativos trimestrais — flag: --desde ANO
│       ├── ingest_notas_explicativas.py  # texto completo do ITR/DFP (sob demanda)
│       └── extract_pdf.py          # extração de texto dos PDFs do IPE
│   └── analysis/                   # consistência dos demonstrativos (no job semanal, após DFP/ITR)
│       ├── consistency_utils.py    # latest_rows, tolerância, consistency_runs/flags
│       ├── check_hierarchy_sums.py # Camada 1: soma hierárquica intra-documento (regressão da ingestão)
│       ├── check_cross_period.py   # Camada 2: cruzamento entre filings (reapresentação)
│       ├── check_granularity.py    # Camada 3: linhas sem par entre filings (renumeração, Outros, irmão)
│       ├── check_text_stability.py # Camada 5 (+4): trilha temporal de nomes/códigos por pai (cd_conta_ds_timeline)
│       ├── derive_quarters.py      # Camada 6: desacúmulo por safra → demonstrativos_trimestrais
│       └── run_all.py              # orquestrador: --layer 2 --cnpj|--full
├── tests/                          # pytest (sem rede, tudo mockado)
├── docs/superpowers/plans/         # registros de design de features já implementadas
└── logs/                           # logs do update semanal (não versionado)
```

### Fontes de dados

| Script | Fonte | Tabelas populadas | Cadência |
|---|---|---|---|
| `catalog.py` | B3 API + CVM | `company_catalog.csv` (arquivo) | ao expandir cobertura |
| `add_companies.py` | `company_catalog.csv` | `watchlist.csv` (arquivo) | ao expandir cobertura |
| `ingest_companies.py` | `watchlist.csv` | `companies` | após mudar watchlist |
| `ingest_ipe.py` | IPE ZIPs anuais | `ipe_docs` (metadados) | semanal (seg após 8h30) |
| `extract_pdf.py` | PDFs do `link_download` | `ipe_docs.texto_extraido`, `ipe_docs_fts` | semanal, em lotes |
| `ingest_vlmo.py` | VLMO ZIPs anuais | `vlmo_posicao`, `vlmo_movimentacoes` | semanal |
| `ingest_recompra.py` | Recompra ZIPs | `recompra_programas` | semanal |
| `ingest_fre.py` | FRE ZIPs anuais | `fre_capital_social`, `fre_posicao_acionaria`, `fre_remuneracao_orgao` | semanal |
| `ingest_dfp.py` | DFP ZIPs anuais | `demonstrativos_contabeis` (fonte='DFP'; grava `st_conta_fixa`) | semanal |
| `ingest_itr.py` | ITR ZIPs anuais | `demonstrativos_contabeis` (fonte='ITR'; trimestre isolado + acumulado; grava `st_conta_fixa`) | semanal |
| `ingest_notas_explicativas.py` | Pacote ZIP do filing (rad.cvm.gov.br) | `notas_explicativas`, `notas_explicativas_fts` | sob demanda |

## Análise de consistência dos demonstrativos

Scripts em `scripts/analysis/` cruzam os quadros de `demonstrativos_contabeis` e gravam achados em
`consistency_runs` / `consistency_flags` (metadados; o valor publicado pela CVM nunca é alterado).
As Camadas 1, 2, 3, 5 e 6 rodam no job semanal logo após `ingest_dfp`/`ingest_itr` (base inteira, ~1,5 min).
À mão, para uma empresa ou para forçar agora:

```bash
cd scripts/analysis && source ../../.venv/bin/activate
python run_all.py --layer 2 --cnpj 84.429.695/0001-11   # uma empresa (~1 s)
python run_all.py --layer 1,2,3,5,6 --cnpj 84.429.695/0001-11 # todas as camadas
python run_all.py --layer 2 --full                       # base inteira (145 empresas, ~1,5 min)
```

| Camada | Script | O que detecta |
|---|---|---|
| 1 | `check_hierarchy_sums.py` | Dentro de cada documento, pai = Σ filhos diretos e fórmulas de nível 2 (DRE/DFC): `nao_detalhado` (pai sem abertura), `pai_vazio`, `divergencia`, `divergencia_formula`. Exceções: `6.05` = saldo final − inicial, `3.99` ignorada. |
| 2 | `check_cross_period.py` | O mesmo período em filings diferentes (DFP × ITRs seguintes × DFP seguinte): `reapresentacao` quando o total diverge, `reclassificacao` quando só sublinhas mudam. Baseline = filing mais antigo. |
| 3 | `check_granularity.py` | Linhas que existem só num dos filings do par: `renumerado` (mesmo nome ou mesmo valor em outro código), `zero_padding`, `reclassificado_em_outros`, `reclassificado_em_irmao` (pai inalterado), `divergencia_nao_explicada`. |
| 5 (+4) | `check_text_stability.py` | Trilha temporal de cada linha (pai + nome) entre filings consecutivos em `cd_conta_ds_timeline`: `renumerado`, `reformulacao`/`ambiguo` (similaridade textual), `nova`, `removida`. |
| 6 | `derive_quarters.py` | Valor de cada trimestre da DRE/DFC_MI/DVA por conta e safra em `demonstrativos_trimestrais`: publicado (DRE 1T–3T) ou derivado por diferença de acumulados da mesma safra (4T = DFP − 3T); flags `reapresentacao_intra_ano`, `componente_reapresentado`, `linha_sem_par`, `sem_3t`. |

Plano e camadas seguintes: `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md`.

---

## Histórico

**18/09/2026 — casamento de linhas no desacúmulo (Camada 6).** A Camada 6 subtraía acumulados casando as linhas por
`cd_conta`, que não é estável entre filings: a empresa renumera as contas que cria (`st_conta_fixa = 'N'`) entre
trimestres e o DFP usa um layout diferente do ITR. Resultado: 21% das linhas derivadas da DFC no 2T e no 3T e 39% no 4T
subtraíam uma linha de outra, quase sempre sem flag — cerca de 24,6 mil valores errados só na DFC de 2T e 3T, em todas
as 145 empresas. O caso relatado foi a Multiplan, cuja `6.03.08` da DFC é "Dividendos" no 1T e "Pagamento de encargos
sobre debêntures" no 2T: o 2T26 saía −249,5 mi em vez de −202,1 mi.

Passou a usar `match_filings`, a escada de casamento da Camada 5, e a gravar o par em `cd_conta_b`/`casamento`. Pares de
similaridade ambígua (0,55 a 0,75) não são casados automaticamente: viram `par_ambiguo`, fila de revisão em
`consistency_flags`. Os testes contra o dado bruto acharam um segundo caso da mesma família: na revisão do plano dos
bancos, entre o ITR do 3T/2017 e o DFP/2017, o Itaú teve `3.01.02` mudando de "Receita de Dividendos" para o resultado
de câmbio — por isso o casamento da Camada 6 não confia no código fixo da CVM sem olhar o nome (a Camada 5 mantém a
regra antiga). Plano, medições e decisões em
`docs/superpowers/plans/2026-09-18-fase6-casamento-de-linhas-no-desacumulo.md`.

Medido na base inteira depois da correção (safra `original`, 106 s de execução, 1.797.994 linhas):

| tipo_doc | trimestre | linhas | com valor | mesmo código | renumerado | reformulação | ambíguo | sem par |
|---|---|---|---|---|---|---|---|---|
| DFC_MI | 2 | 93.391 | 89,8% | 68.425 | 8.487 | 6.989 | 1.908 | 7.199 |
| DFC_MI | 3 | 87.891 | 91,1% | 65.548 | 8.278 | 6.276 | 1.577 | 5.853 |
| DFC_MI | 4 | 100.763 | 78,0% | 51.442 | 14.725 | 12.422 | 3.222 | 11.193 |
| DRE | 2 | 55.611 | 100,0% | 52.892 | 369 | 610 | 142 | 1.382 |
| DRE | 3 | 51.946 | 100,0% | 49.636 | 357 | 519 | 120 | 1.140 |
| DRE | 4 | 56.562 | 87,1% | 47.681 | 637 | 930 | 230 | 2.097 |
| DVA | 2 | 77.891 | 98,4% | 75.875 | 379 | 395 | 101 | 811 |
| DVA | 3 | 72.399 | 98,5% | 70.802 | 230 | 310 | 48 | 763 |
| DVA | 4 | 80.072 | 88,8% | 69.927 | 522 | 641 | 157 | 1.748 |

As colunas `renumerado` e `reformulação` são a massa que antes era subtraída errado. A cobertura da DFC no 4T caiu de
84% para 78%: linhas que não existem no acumulado anterior agora são NULL em vez de um número inventado. Na DRE, 1.512
flags de `reapresentacao_intra_ano` desapareceram (13.024 → 11.512) — eram artefato do casamento errado, não divergência
da fonte. A fila `par_ambiguo` tem 14.993 flags, 57% delas no mesmo código; o limiar é ajustável por `--sim-alto`.

O projeto começou em Supabase/PostgreSQL e migrou para SQLite local em junho de 2026 (um arquivo, zero serviços). O MCP passou de `mcp-server-sqlite` (npx) para um servidor Python próprio em setembro de 2026. Os workflows de GitHub Actions foram removidos: toda a ingestão roda localmente.

## Testes

```bash
.venv/bin/python -m pytest tests/ -q
```
