#!/bin/bash
# Atualização semanal da base CVM Research (SQLite local).
# Roda todos os ingestores + consistência dos demonstrativos (Camadas 1 a 6) +
# extração de PDFs novos. Pensado para o launchd
# (segunda-feira ~9h, após a CVM publicar os ZIPs entre 8h00 e 8h30), mas pode
# ser executado manualmente a qualquer momento:
#   bash scripts/update_weekly.sh
#
# Variáveis opcionais:
#   EXTRACT_LIMIT=1000   máximo de PDFs a extrair por execução (default 1000)
#   RETRY_FAILED=1       após os novos, re-tenta PDFs marcados como falha (default 0)

set -u
set -o pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
LOCK_DIR="$LOG_DIR/.update_weekly.lock"
LOG_FILE="$LOG_DIR/update_$(date +%Y%m%d_%H%M%S).log"
EXTRACT_LIMIT="${EXTRACT_LIMIT:-1000}"
RETRY_FAILED="${RETRY_FAILED:-0}"

mkdir -p "$LOG_DIR"

# Evita duas execuções simultâneas (lock atômico via mkdir)
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$(date '+%F %T') Já existe uma execução em andamento ($LOCK_DIR). Abortando." | tee -a "$LOG_FILE"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG_FILE"; }

if [ ! -x "$VENV_PY" ]; then
  log "ERRO: .venv não encontrado em $VENV_PY — rode: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

cd "$PROJECT_DIR/scripts/ingest" || exit 1

START=$(date +%s)
FAILED=()

run_step() {
  local name="$1"; shift
  log "==> $name: $*"
  if "$VENV_PY" "$@" >>"$LOG_FILE" 2>&1; then
    log "    OK  $name"
  else
    log "    FALHOU $name (exit $?) — ver $LOG_FILE"
    FAILED+=("$name")
  fi
}

log "===== Início da atualização semanal — projeto: $PROJECT_DIR ====="

# Impede o Mac de dormir por inatividade enquanto o script roda
if command -v caffeinate >/dev/null; then caffeinate -i -w $$ & fi

run_step "companies" ingest_companies.py
run_step "ipe"       ingest_ipe.py
run_step "vlmo"      ingest_vlmo.py
run_step "recompra"  ingest_recompra.py
run_step "fre"       ingest_fre.py
run_step "dfp"       ingest_dfp.py
run_step "itr"       ingest_itr.py
# Consistência dos demonstrativos — depende de DFP/ITR recém-ingeridos;
# idempotente. Camada 1 (soma hierárquica: regressão da ingestão), Camada 2
# (reapresentações entre filings), Camada 3 (linhas sem par entre filings) e
# Camada 5 (trilha temporal de nomes/códigos, cd_conta_ds_timeline) e
# Camada 6 (desacúmulo → demonstrativos_trimestrais; usa os resumos da 2),
# ~1–2 min cada na base inteira. Pulado se
# os dois ingestores falharam (não haveria dado novo para checar).
if [[ " ${FAILED[*]} " == *" dfp "* && " ${FAILED[*]} " == *" itr "* ]]; then
  log "==> consistency: pulado (dfp e itr falharam)"
else
  run_step "consistency_l1" ../analysis/run_all.py --layer 1 --full
  run_step "consistency_l2" ../analysis/run_all.py --layer 2 --full
  run_step "consistency_l3" ../analysis/run_all.py --layer 3 --full
  run_step "consistency_l5" ../analysis/run_all.py --layer 5 --full
  run_step "consistency_l6" ../analysis/run_all.py --layer 6 --full
fi
run_step "extract_pdf" extract_pdf.py --limite "$EXTRACT_LIMIT"
if [ "$RETRY_FAILED" = "1" ]; then
  run_step "extract_pdf_retry" extract_pdf.py --retry-failed --limite "$EXTRACT_LIMIT"
fi

# Resumo do banco após a atualização
DB="$PROJECT_DIR/cvm_research.db"
if command -v sqlite3 >/dev/null; then
  log "Resumo: $(sqlite3 "$DB" "SELECT 'ipe_docs='||COUNT(*)||' com_texto='||SUM(texto_extraido IS NOT NULL)||' max_entrega='||MAX(data_entrega) FROM ipe_docs")"
fi

# Mantém apenas os 12 logs mais recentes
ls -1t "$LOG_DIR"/update_*.log 2>/dev/null | tail -n +13 | xargs -I{} rm -f "{}"

ELAPSED=$(( $(date +%s) - START ))
if [ ${#FAILED[@]} -eq 0 ]; then
  log "===== Concluído sem erros em $((ELAPSED/60)) min ====="
  exit 0
else
  log "===== Concluído com falhas (${FAILED[*]}) em $((ELAPSED/60)) min ====="
  exit 1
fi
