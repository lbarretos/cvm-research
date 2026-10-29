# TODOS

Backlog do projeto. O que já foi feito está no `git log` e na seção "Histórico" do README.

**Roadmap atual:** [`docs/proximos-passos/README.md`](docs/proximos-passos/README.md), com as etapas de leitura
por LLM e padronização dos demonstrativos. Cada etapa tem avaliação, proposta, stress test e critério de pronto.

## Dados

- [ ] **Extrair docs/financials das empresas de Restructuring** — AERI3, PCAR3, BOBR4, LUPA3, PMAM3 entraram no `watchlist.csv` (página "Restructuring" do Notion) mas ainda não foram carregadas. Rodar `python scripts/ingest/ingest_companies.py`, depois `bash bootstrap.sh --sem-pdf` (usa o watchlist.csv como está; ou os ingestores `ingest_ipe/vlmo/recompra/fre/dfp/itr` com `--desde`), o tratamento (`cd scripts/analysis && python run_all.py --layer 1,2,3,5,6 --full`) e `bash bootstrap.sh --so-pdf` para o texto dos PDFs. Conferir `codigo_cvm` de cada uma contra `cad_cia_aberta.csv` (foi preenchido por fonte web; LUPA3 e PMAM3 de fonte única) e o CNPJ da PMAM3 (0004-79). Considerar `ingest_notas_explicativas.py` para os últimos trimestres (planos de RJ/RE ficam em notas e fatos relevantes).
- [ ] **PDFs com falha de extração** — 5.586 docs em `ipe_docs` com `extracao_falhou=1` (a maioria digitalizados sem camada de texto). Avaliar OCR (`ocrmypdf`/`tesseract`) para os prioritários (Fato Relevante, Assembleia) ou aceitar o gap. `EXTRACT_LIMIT=2000 RETRY_FAILED=1 bash scripts/update_weekly.sh` re-tenta os transitórios.
- [ ] **`recompra_quantidades` e `recompra_intermediarios`** — existem no schema, 0 linhas, o ingestor não as popula. Popular a partir dos CSVs do ZIP de recompra ou remover do `schema.sql`.
- [ ] **Notas explicativas** — cobertura mínima (só Frasle 1T26/2T26). Definir critério de ingestão (ex: últimos 8 trimestres das empresas em análise ativa) e um comando de lote por empresa.
- [ ] **Tickers assumidos** — 34 linhas do `watchlist.csv` com `auto:assumed` (lote de julho/2026). Conferir na B3 e limpar a flag.
- [ ] **IPE 2009–2014** — os ZIPs da CVM desses anos vêm sem `Protocolo_Entrega` e são descartados. Verificar se há outra chave utilizável ou documentar como limite definitivo.

## Operação

- [x] **Job semanal no launchd** — instalado em 16/09/2026; exigiu Acesso Total ao Disco para `/bin/bash` (projeto em `~/Documents`). Conferir na segunda seguinte com `bash scripts/install_weekly_launchd.sh --status`.
- [ ] **Claude desktop app** — `claude_desktop_config.json` está sem o MCP `cvm-research` (só o Claude Code está configurado). Adicionar se for usar o app.
- [ ] **`VACUUM` periódico** — o banco tem ~12 GB; após grandes reextrações vale um `VACUUM` (precisa de espaço livre igual ao tamanho do banco).

## Código

- [~] **Fila `par_ambiguo` da Camada 6** — parte feita na Etapa 6: `linha_decisao` + `python linha_economica.py --listar-ambiguos / --decidir` guardam a decisão e o encadeamento da `linha_empresa` a respeita. Falta a Camada 6 (`demonstrativos_trimestrais`) ler `linha_decisao` para casar os pares ambíguos que ela deixou sem valor.
- [ ] **`text_similarity` é assimétrica** — `difflib` dá score diferente conforme a ordem dos argumentos, e em pares reais isso cruza o limiar de 0,75 (0,7532 contra 0,7273). Hoje todas as chamadas usam `(anterior, atual)`, então é consistente, mas frágil. Tornar simétrica (`max` ou média das duas ordens) exigiria re-rodar a Camada 5 inteira e revisar os limiares.
- [ ] **Camada 5 e o plano de contas dos bancos** — `cd_conta_ds_timeline` ainda marca `estavel` quando uma conta `S` muda de nome no mesmo código, e por isso descreve a re-letragem do plano COSIF de 2017 como se nada tivesse acontecido (ver Itaú, DRE 3.01.02). A Camada 6 já não confia nisso (`codigo_fixo_confiavel=False`); avaliar se a Camada 5 deveria seguir.

- [ ] **Testes de integração leves** — hoje tudo é mockado; um teste que roda `setup.sh` num banco temporário e valida as views (`vw_dre`, `vw_balanco`) contra fixtures pequenas pegaria regressões de schema.
- [ ] **`extract_pdf.py` no fluxo semanal** — `EXTRACT_LIMIT` default 1000 pode não acompanhar semanas com muitos docs; medir e ajustar.
