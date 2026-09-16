# TODOS

Backlog do projeto. O que já foi feito está no `git log` e na seção "Histórico" do README.

## Dados

- [ ] **PDFs com falha de extração** — 5.586 docs em `ipe_docs` com `extracao_falhou=1` (a maioria digitalizados sem camada de texto). Avaliar OCR (`ocrmypdf`/`tesseract`) para os prioritários (Fato Relevante, Assembleia) ou aceitar o gap. `EXTRACT_LIMIT=2000 RETRY_FAILED=1 bash scripts/update_weekly.sh` re-tenta os transitórios.
- [ ] **`recompra_quantidades` e `recompra_intermediarios`** — existem no schema, 0 linhas, o ingestor não as popula. Popular a partir dos CSVs do ZIP de recompra ou remover do `schema.sql`.
- [ ] **Notas explicativas** — cobertura mínima (só Frasle 1T26/2T26). Definir critério de ingestão (ex: últimos 8 trimestres das empresas em análise ativa) e um comando de lote por empresa.
- [ ] **Tickers assumidos** — 34 linhas do `watchlist.csv` com `auto:assumed` (lote de julho/2026). Conferir na B3 e limpar a flag.
- [ ] **IPE 2009–2014** — os ZIPs da CVM desses anos vêm sem `Protocolo_Entrega` e são descartados. Verificar se há outra chave utilizável ou documentar como limite definitivo.

## Operação

- [ ] **Job semanal no launchd** — instalado em 16/09/2026 mas bloqueado pelo TCC (projeto em `~/Documents`). Dar Acesso Total ao Disco ao `/bin/bash` ou mover o projeto para fora de `~/Documents`, depois `bash scripts/install_weekly_launchd.sh --run-now` e conferir `logs/`.
- [ ] **Claude desktop app** — `claude_desktop_config.json` está sem o MCP `cvm-research` (só o Claude Code está configurado). Adicionar se for usar o app.
- [ ] **`VACUUM` periódico** — o banco tem ~12 GB; após grandes reextrações vale um `VACUUM` (precisa de espaço livre igual ao tamanho do banco).

## Código

- [ ] **Testes de integração leves** — hoje tudo é mockado; um teste que roda `setup.sh` num banco temporário e valida as views (`vw_dre`, `vw_balanco`) contra fixtures pequenas pegaria regressões de schema.
- [ ] **`extract_pdf.py` no fluxo semanal** — `EXTRACT_LIMIT` default 1000 pode não acompanhar semanas com muitos docs; medir e ajustar.
