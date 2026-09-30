#!/bin/bash
# Atualização semanal da base CVM Research (SQLite local).
# Roda todos os ingestores + consistência dos demonstrativos (Camadas 1 a 6) +
# extração de PDFs novos. Pensado para o launchd, mas pode ser executado
# manualmente a qualquer momento (sem flag, roda sempre):
#   bash scripts/update_weekly.sh
#
# Flags:
#   --se-vencido   só roda se ainda não houve execução bem-sucedida desde a última
#                  publicação da CVM (segunda 9h por padrão); senão sai em segundos.
#                  É o modo do launchd, que dispara no login, toda segunda 9h e a
#                  cada 4 h — assim uma segunda perdida (Mac desligado) é recuperada
#                  no mesmo dia, sem rodar a carga mais de uma vez por semana.
#   --verificar    só diz se a execução está vencida (exit 0) ou em dia (exit 1).
#
# Variáveis opcionais:
#   EXTRACT_LIMIT=1000   máximo de PDFs a extrair por execução (default 1000)
#   RETRY_FAILED=1       após os novos, re-tenta PDFs marcados como falha (default 0)
#   CVM_DIA_SEMANA=1     dia da publicação semanal (0/7=domingo, 1=segunda …)
#   CVM_HORA=9           hora a partir da qual a publicação da semana está disponível
#   MAX_TENTATIVAS=3     no modo --se-vencido, tentativas com falha por semana
#   ESPERA_REDE_SEG=300  quanto esperar a rede/DNS subir antes de desistir
#   UPDATE_LOG_DIR       pasta de logs e marcadores (default: logs/)
#   NOW_EPOCH            "agora" em segundos Unix (só para testes)

set -u
set -o pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="${UPDATE_LOG_DIR:-$PROJECT_DIR/logs}"
LOCK_DIR="$LOG_DIR/.update_weekly.lock"
STAMP_FILE="$LOG_DIR/.ultimo_sucesso"       # epoch + data legível da última execução sem falhas
TENTATIVAS_FILE="$LOG_DIR/.tentativas"      # epoch de cada execução iniciada desde o último sucesso
LOG_FILE="$LOG_DIR/update_$(date +%Y%m%d_%H%M%S).log"
EXTRACT_LIMIT="${EXTRACT_LIMIT:-1000}"
RETRY_FAILED="${RETRY_FAILED:-0}"
CVM_DIA_SEMANA="${CVM_DIA_SEMANA:-1}"
CVM_HORA="${CVM_HORA:-9}"
MAX_TENTATIVAS="${MAX_TENTATIVAS:-3}"
ESPERA_REDE_SEG="${ESPERA_REDE_SEG:-300}"
URL_REDE="${URL_REDE:-https://dados.cvm.gov.br/}"
DIAS_ALERTA_IPE=9   # MAX(data_entrega) mais antigo que isso = base parou de receber o IPE

MODO=sempre
case "${1:-}" in
  --se-vencido) MODO=se_vencido ;;
  --verificar)  MODO=verificar ;;
  "") ;;
  *) echo "Uso: $0 [--se-vencido | --verificar]" >&2; exit 2 ;;
esac

mkdir -p "$LOG_DIR"

# Mensagens antes de a execução começar de fato vão só para a saída padrão
# (launchd.out.log): um log update_*.log por disparo de 4 h empurraria os logs
# reais para fora da rotação.
say() { echo "$(date '+%F %T') $*"; }
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG_FILE"; }

agora() { echo "${NOW_EPOCH:-$(date +%s)}"; }

# date(1) formatando um epoch: -r no macOS, -d @ no GNU
data_de() { date -r "$1" "$2" 2>/dev/null || date -d "@$1" "$2"; }

# Epoch do último <CVM_DIA_SEMANA> às <CVM_HORA>:00 que já passou — o momento a
# partir do qual os ZIPs da semana estão publicados. Na virada do horário de verão
# o marco pode andar 1 h, o que não importa aqui.
ultimo_marco() {
  local now=$1 dow h m s alvo dias marco
  read -r dow h m s <<<"$(data_de "$now" '+%u %H %M %S')"
  alvo=$CVM_DIA_SEMANA; [ "$alvo" -eq 0 ] && alvo=7
  dias=$(( (dow - alvo + 7) % 7 ))
  marco=$(( now - (10#$h * 3600 + 10#$m * 60 + 10#$s) - dias * 86400 + CVM_HORA * 3600 ))
  [ "$marco" -gt "$now" ] && marco=$(( marco - 7 * 86400 ))
  echo "$marco"
}

ultimo_sucesso() {
  local v
  v=$(head -1 "$STAMP_FILE" 2>/dev/null | cut -d' ' -f1)
  [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}

# Exit 0 = vencida (deve rodar); 1 = em dia ou tentativas esgotadas. Diz o porquê.
verificar_vencido() {
  local now marco ultimo n
  now=$(agora); marco=$(ultimo_marco "$now"); ultimo=$(ultimo_sucesso)
  if [ "$ultimo" -ge "$marco" ]; then
    echo "em dia: último sucesso $(data_de "$ultimo" '+%F %T'); próxima janela $(data_de $(( marco + 7 * 86400 )) '+%F %T')"
    return 1
  fi
  n=$(awk -v m="$marco" '$1 >= m' "$TENTATIVAS_FILE" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -ge "$MAX_TENTATIVAS" ]; then
    echo "vencida, mas já houve $n tentativas com falha desde $(data_de "$marco" '+%F %T'); aguardando a próxima janela ou execução manual (ver logs/update_*.log)"
    return 1
  fi
  if [ "$ultimo" -eq 0 ]; then
    echo "vencida: nenhuma execução bem-sucedida registrada"
  else
    echo "vencida: último sucesso $(data_de "$ultimo" '+%F %T') é anterior à publicação de $(data_de "$marco" '+%F %T')"
  fi
  return 0
}

if [ "$MODO" = verificar ]; then
  verificar_vencido
  exit $?
fi

# Evita duas execuções simultâneas (lock atômico via mkdir). O PID fica dentro do
# lock: se o dono morreu sem limpar (Mac desligado no meio da carga), o lock é
# tomado de volta em vez de travar todas as execuções seguintes.
pegar_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then echo $$ >"$LOCK_DIR/pid"; return 0; fi
  local pid
  pid=$(cat "$LOCK_DIR/pid" 2>/dev/null)
  if [ -n "$pid" ] && ps -p "$pid" -o command= 2>/dev/null | grep -q update_weekly; then
    return 1
  fi
  say "Lock órfão (pid ${pid:-?} não está rodando); removendo."
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || return 1
  echo $$ >"$LOCK_DIR/pid"
}

if ! pegar_lock; then
  say "Já existe uma execução em andamento ($LOCK_DIR, pid $(cat "$LOCK_DIR/pid" 2>/dev/null)). Saindo."
  exit 0
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

# Conferido depois do lock: se outra execução acabou de terminar, o marcador já é o novo
if [ "$MODO" = se_vencido ]; then
  if ! MOTIVO=$(verificar_vencido); then
    say "Nada a fazer — $MOTIVO"
    exit 0
  fi
  say "Execução $MOTIVO"
fi

# Logo após acordar/ligar o DNS pode ainda não responder ("nodename nor servname
# provided"); espera a CVM ficar acessível em vez de falhar os ingestores.
esperar_rede() {
  local inicio
  inicio=$(date +%s)
  while :; do
    curl -s -o /dev/null --head --max-time 10 "$URL_REDE" && return 0
    [ $(( $(date +%s) - inicio )) -ge "$ESPERA_REDE_SEG" ] && return 1
    sleep 10
  done
}

if ! esperar_rede; then
  say "ERRO: $URL_REDE inacessível após ${ESPERA_REDE_SEG}s — sem rede. Nada foi executado; tenta de novo no próximo disparo."
  exit 1
fi

if [ ! -x "$VENV_PY" ]; then
  log "ERRO: .venv não encontrado em $VENV_PY — rode: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

INICIO=$(agora)
echo "$INICIO" >>"$TENTATIVAS_FILE"

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
# (reapresentações entre filings), Camada 3 (linhas sem par entre filings),
# Camada 5 (trilha temporal de nomes/códigos, cd_conta_ds_timeline) e
# Camada 6 (desacúmulo → demonstrativos_trimestrais; usa os resumos da 2),
# ~1–2 min cada na base inteira. Pulado se
# os dois ingestores falharam (não haveria dado novo para checar).
if [[ " ${FAILED[*]:-} " == *" dfp "* && " ${FAILED[*]:-} " == *" itr "* ]]; then
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
  # A CVM publica o IPE toda semana: documento mais novo com mais de 9 dias quer
  # dizer que a ingestão não está trazendo nada novo (job parado ou fonte travada).
  DIAS_IPE=$(sqlite3 "$DB" "SELECT CAST(julianday('now') - julianday(MAX(data_entrega)) AS INTEGER) FROM ipe_docs")
  if [ -n "$DIAS_IPE" ] && [ "$DIAS_IPE" -gt "$DIAS_ALERTA_IPE" ]; then
    log "WARNING: ipe_docs está defasado — MAX(data_entrega) tem $DIAS_IPE dias (limite $DIAS_ALERTA_IPE). Conferir o passo 'ipe' acima e o ZIP do ano em dados.cvm.gov.br."
  fi
fi

# Mantém apenas os 12 logs mais recentes
ls -1t "$LOG_DIR"/update_*.log 2>/dev/null | tail -n +13 | xargs -I{} rm -f "{}"

ELAPSED=$(( $(date +%s) - START ))
if [ ${#FAILED[@]} -eq 0 ]; then
  # Vale o início: os ZIPs baixados são os disponíveis naquele momento
  echo "$INICIO $(data_de "$INICIO" '+%F %T')" >"$STAMP_FILE"
  rm -f "$TENTATIVAS_FILE"
  log "===== Concluído sem erros em $((ELAPSED/60)) min ====="
  exit 0
else
  log "===== Concluído com falhas (${FAILED[*]}) em $((ELAPSED/60)) min ====="
  exit 1
fi
