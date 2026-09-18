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
As Camadas 1 e 2 rodam no job semanal logo após `ingest_dfp`/`ingest_itr` (base inteira, ~1,5 min).
À mão, para uma empresa ou para forçar agora:

```bash
cd scripts/analysis && source ../../.venv/bin/activate
python run_all.py --layer 2 --cnpj 84.429.695/0001-11   # uma empresa (~1 s)
python run_all.py --layer 1,2 --cnpj 84.429.695/0001-11 # as duas camadas
python run_all.py --layer 2 --full                       # base inteira (145 empresas, ~1,5 min)
```

| Camada | Script | O que detecta |
|---|---|---|
| 1 | `check_hierarchy_sums.py` | Dentro de cada documento, pai = Σ filhos diretos e fórmulas de nível 2 (DRE/DFC): `nao_detalhado` (pai sem abertura), `pai_vazio`, `divergencia`, `divergencia_formula`. Exceções: `6.05` = saldo final − inicial, `3.99` ignorada. |
| 2 | `check_cross_period.py` | O mesmo período em filings diferentes (DFP × ITRs seguintes × DFP seguinte): `reapresentacao` quando o total diverge, `reclassificacao` quando só sublinhas mudam. Baseline = filing mais antigo. |

Plano e camadas seguintes: `docs/superpowers/plans/2026-09-17-consistencia-dados-financeiros.md`.

---

## Histórico

O projeto começou em Supabase/PostgreSQL e migrou para SQLite local em junho de 2026 (um arquivo, zero serviços). O MCP passou de `mcp-server-sqlite` (npx) para um servidor Python próprio em setembro de 2026. Os workflows de GitHub Actions foram removidos: toda a ingestão roda localmente.

## Testes

```bash
.venv/bin/python -m pytest tests/ -q
```
