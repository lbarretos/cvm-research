#!/usr/bin/env bash
# Carga inicial completa: banco vazio -> base pesquisável, com os dados tratados.
#
# Faz, em ordem, o que o README descreve passo a passo, e mais o que ele omitia:
# as camadas de consistência (sem elas, demonstrativos_trimestrais e consistency_flags
# ficam vazias) e o laço de extração de PDF (extract_pdf.py processa um lote por
# chamada, então uma invocação só não dá conta de ~170 mil documentos).
#
# É retomável: todo passo é idempotente e pode ser interrompido com Ctrl-C e
# recomeçado. Rodar de novo num banco já cheio é barato nos ingestores (eles
# reprocessam os ZIPs e fazem UPSERT) e regenera as camadas de análise.
#
# Uso (na raiz do projeto, depois de `bash setup.sh` e do .env):
#   bash bootstrap.sh                  # tudo: histórico + análise + PDFs
#   bash bootstrap.sh --sem-pdf        # pula a extração de texto (a parte mais demorada)
#   bash bootstrap.sh --so-pdf         # só retoma a extração de texto
#   bash bootstrap.sh --so-analise     # só regenera as camadas de consistência
#   IPE_DESDE=2020 DFP_DESDE=2018 bash bootstrap.sh   # menos histórico, mais rápido
#
# Tempo de referência num Mac M-series com banda boa, para as 145 empresas do
# watchlist.csv: ingestores 30-60 min, análise ~6 min, PDFs 12-24 h (~170 mil
# documentos, limitado pela CVM, não pela máquina). O banco final tem ~12 GB.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

IPE_DESDE="${IPE_DESDE:-2015}"      # ZIPs de 2009-2014 vêm sem Protocolo_Entrega e são descartados
VLMO_DESDE="${VLMO_DESDE:-2018}"    # VLMO estruturado só existe a partir de 2018
FRE_DESDE="${FRE_DESDE:-2010}"
DFP_DESDE="${DFP_DESDE:-2010}"
ITR_DESDE="${ITR_DESDE:-2011}"
PDF_LOTE="${PDF_LOTE:-500}"         # documentos por chamada de extract_pdf.py

FAZER_INGEST=1; FAZER_ANALISE=1; FAZER_PDF=1
case "${1:-}" in
  --sem-pdf)    FAZER_PDF=0 ;;
  --so-pdf)     FAZER_INGEST=0; FAZER_ANALISE=0 ;;
  --so-analise) FAZER_INGEST=0; FAZER_PDF=0 ;;
  --help|-h)    sed -n '2,25p' "$0"; exit 0 ;;
  "")           ;;
  *)            echo "opção desconhecida: $1 (use --help)" >&2; exit 2 ;;
esac

PY="$PROJECT_DIR/.venv/bin/python"
DB="$PROJECT_DIR/cvm_research.db"
START=$(date +%s)

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
passo() { log "==> $*"; }

# ── Pré-requisitos ───────────────────────────────────────────────────────────
[ -x "$PY" ] || { echo "ERRO: .venv não encontrada. Rode: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }
[ -f .env ] || { echo "ERRO: .env não encontrado. Rode: echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env" >&2; exit 1; }
[ -f "$DB" ] || { echo "ERRO: cvm_research.db não encontrado. Rode: bash setup.sh" >&2; exit 1; }
command -v sqlite3 >/dev/null || { echo "ERRO: sqlite3 não encontrado no PATH." >&2; exit 1; }

log "projeto: $PROJECT_DIR"
log "watchlist: $(($(wc -l < watchlist.csv) - 1)) empresas"

cd "$PROJECT_DIR/scripts/ingest"

# ── 1. Dados brutos ──────────────────────────────────────────────────────────
if [ "$FAZER_INGEST" = 1 ]; then
  passo "empresas (watchlist.csv -> tabela companies)"
  "$PY" ingest_companies.py

  passo "IPE — catálogo de documentos, desde $IPE_DESDE"
  "$PY" ingest_ipe.py --desde "$IPE_DESDE"

  passo "VLMO — insider trading, desde $VLMO_DESDE"
  "$PY" ingest_vlmo.py --desde "$VLMO_DESDE"

  passo "Recompra — programas de recompra"
  "$PY" ingest_recompra.py

  passo "FRE — capital, acionistas, remuneração, desde $FRE_DESDE"
  "$PY" ingest_fre.py --desde "$FRE_DESDE"

  passo "DFP — demonstrativos anuais, desde $DFP_DESDE"
  "$PY" ingest_dfp.py --historico --desde "$DFP_DESDE"

  passo "ITR — demonstrativos trimestrais, desde $ITR_DESDE"
  "$PY" ingest_itr.py --desde "$ITR_DESDE"
fi

# ── 2. Tratamento (camadas de consistência) ──────────────────────────────────
# Sem este bloco, consistency_flags, cd_conta_ds_timeline e demonstrativos_trimestrais
# ficam vazias e as queries trimestrais do CLAUDE.md não respondem nada.
if [ "$FAZER_ANALISE" = 1 ]; then
  cd "$PROJECT_DIR/scripts/analysis"
  passo "consistência — Camadas 1, 2, 3, 5 e 6 (a 3 depende da 2; a 6, da 2 e da 5)"
  "$PY" run_all.py --layer 1,2,3,5,6 --full
  cd "$PROJECT_DIR/scripts/ingest"
fi

# ── 3. Texto dos PDFs ────────────────────────────────────────────────────────
# extract_pdf.py processa um lote por chamada e escolhe os pendentes
# (texto_extraido IS NULL AND extracao_falhou = 0), então o laço avança sozinho e
# pode ser interrompido a qualquer momento.
if [ "$FAZER_PDF" = 1 ]; then
  passo "texto dos PDFs do IPE — lotes de $PDF_LOTE, até não sobrar pendente"
  while :; do
    PEND=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ipe_docs WHERE texto_extraido IS NULL AND extracao_falhou = 0")
    [ "$PEND" -gt 0 ] || { log "extração concluída: nenhum documento pendente"; break; }
    log "pendentes: $PEND"
    "$PY" extract_pdf.py --limite "$PDF_LOTE"
    DEPOIS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ipe_docs WHERE texto_extraido IS NULL AND extracao_falhou = 0")
    # Sem progresso = todos os restantes estão falhando de forma persistente.
    [ "$DEPOIS" -lt "$PEND" ] || { log "lote não avançou; parando (rode com --retry-failed depois)"; break; }
  done
  passo "reconstruindo o índice full-text"
  sqlite3 "$DB" "INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild');"
fi

# ── Resumo ───────────────────────────────────────────────────────────────────
ELAPSED=$(( $(date +%s) - START ))
log "===== concluído em $((ELAPSED / 60)) min ====="
sqlite3 -column "$DB" "
SELECT 'empresas'                   AS tabela, COUNT(*) AS linhas FROM companies
UNION ALL SELECT 'ipe_docs',                   COUNT(*) FROM ipe_docs
UNION ALL SELECT '  com texto extraído',       COUNT(*) FROM ipe_docs WHERE texto_extraido IS NOT NULL
UNION ALL SELECT '  com falha de extração',    COUNT(*) FROM ipe_docs WHERE extracao_falhou = 1
UNION ALL SELECT 'vlmo_movimentacoes',         COUNT(*) FROM vlmo_movimentacoes
UNION ALL SELECT 'demonstrativos_contabeis',   COUNT(*) FROM demonstrativos_contabeis
UNION ALL SELECT 'demonstrativos_trimestrais', COUNT(*) FROM demonstrativos_trimestrais
UNION ALL SELECT 'consistency_flags',          COUNT(*) FROM consistency_flags
UNION ALL SELECT 'cd_conta_ds_timeline',       COUNT(*) FROM cd_conta_ds_timeline;"
echo
log "confira o tratamento com: .venv/bin/python -m pytest tests/ -q"
log "a partir daqui, mantenha a base com: bash scripts/update_weekly.sh"
