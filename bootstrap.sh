#!/usr/bin/env bash
# Carga inicial completa: banco vazio -> base pesquisável, com os dados tratados.
#
# Três blocos, nesta ordem: dados brutos da CVM, camadas de consistência (o
# "tratamento") e texto dos PDFs. Retomável: interrompa com Ctrl-C e rode de novo.
#
# Uso (na raiz do projeto, depois de `bash setup.sh` e do .env):
#
#   bash bootstrap.sh --universo ibov                 # começa do IBOV (~78 empresas)
#   bash bootstrap.sh --universo ibov --desde 2020    # IBOV, documentos de 2020 para cá
#   bash bootstrap.sh --universo minhas.csv           # sua tabela de tickers
#   bash bootstrap.sh --universo todas                # todas as ~443 da B3 ativas
#   bash bootstrap.sh                                 # usa o watchlist.csv como está
#
# Universo (--universo, ou a variável UNIVERSO):
#   ibov | ibrx | todas   carteira da B3 · arquivo .csv/.txt   sua lista de tickers
#   O universo é ADITIVO: soma ao watchlist.csv, nunca remove. Para começar do zero
#   com só o universo escolhido, acrescente --substituir (faz backup antes).
#   Sem --universo, o watchlist.csv do repositório é usado como está.
#
# Período (--desde ANO, ou uma variável por fonte):
#   --desde vale para todas as fontes, respeitando o primeiro ano em que cada uma
#   existe: IPE 2015, VLMO 2018, ITR 2011, DFP e FRE 2010. Pedir antes disso é
#   ajustado para cima com aviso. Controle fino: IPE_DESDE, VLMO_DESDE, FRE_DESDE,
#   DFP_DESDE, ITR_DESDE.
#
# Blocos:
#   --sem-pdf      pula a extração de texto (a parte longa)
#   --so-pdf       só retoma a extração de texto
#   --so-analise   só regenera as camadas de consistência
#   --dry-run      mostra o plano (cobertura, período, blocos) e sai sem baixar nada
#
# Tempo de referência num Mac M-series com banda boa. Para o IBOV (~78 empresas):
# ingestores 20-40 min, análise ~4 min, PDFs 6-12 h. Para as 145 do watchlist do
# repositório: 30-60 min, ~8 min e 12-24 h, com banco final de ~12 GB.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Primeiro ano em que cada fonte existe. Abaixo disso o download volta vazio:
# os ZIPs do IPE de 2009-2014 vêm sem Protocolo_Entrega e são descartados, e o
# VLMO só passou a ser estruturado em 2018.
# Sem array associativo: o bash do macOS é o 3.2, que não tem `declare -A`.
PISO_IPE=2015; PISO_VLMO=2018; PISO_FRE=2010; PISO_DFP=2010; PISO_ITR=2011

IPE_DESDE="${IPE_DESDE:-$PISO_IPE}"
VLMO_DESDE="${VLMO_DESDE:-$PISO_VLMO}"
FRE_DESDE="${FRE_DESDE:-$PISO_FRE}"
DFP_DESDE="${DFP_DESDE:-$PISO_DFP}"
ITR_DESDE="${ITR_DESDE:-$PISO_ITR}"
PDF_LOTE="${PDF_LOTE:-500}"
UNIVERSO="${UNIVERSO:-}"

FAZER_INGEST=1; FAZER_ANALISE=1; FAZER_PDF=1; SUBSTITUIR=0; DESDE=""; DRY=0

# Imprime o cabeçalho deste arquivo (linhas 2 até a última que começa com #).
ajuda() { awk '/^#/ && NR > 1 { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --universo)    UNIVERSO="${2:?--universo precisa de um valor}"; shift 2 ;;
    --desde)       DESDE="${2:?--desde precisa de um ano}"; shift 2 ;;
    --substituir)  SUBSTITUIR=1; shift ;;
    --sem-pdf)     FAZER_PDF=0; shift ;;
    --so-pdf)      FAZER_INGEST=0; FAZER_ANALISE=0; FAZER_PDF=1; shift ;;
    --so-analise)  FAZER_INGEST=0; FAZER_PDF=0; shift ;;
    --dry-run)     DRY=1; shift ;;
    --help|-h)     ajuda; exit 0 ;;
    *)             echo "opção desconhecida: $1 (use --help)" >&2; exit 2 ;;
  esac
done

PY="$PROJECT_DIR/.venv/bin/python"
DB="$PROJECT_DIR/cvm_research.db"
WATCHLIST="$PROJECT_DIR/watchlist.csv"
START=$(date +%s)

log()   { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
passo() { log "==> $*"; }
erro()  { echo "ERRO: $*" >&2; exit 1; }

# ── Pré-requisitos ───────────────────────────────────────────────────────────
[ -x "$PY" ] || erro ".venv não encontrada. Rode: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
[ -f .env ]  || erro ".env não encontrado. Rode: echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env"
[ -f "$DB" ] || erro "cvm_research.db não encontrado. Rode: bash setup.sh"
command -v sqlite3 >/dev/null || erro "sqlite3 não encontrado no PATH."

# ── Período ──────────────────────────────────────────────────────────────────
if [ -n "$DESDE" ]; then
  case "$DESDE" in
    [12][0-9][0-9][0-9]) ;;
    *) erro "--desde espera um ano com 4 dígitos (recebi '$DESDE')" ;;
  esac
  for fonte in IPE VLMO FRE DFP ITR; do
    eval "piso=\$PISO_$fonte"
    ano="$DESDE"
    if [ "$DESDE" -lt "$piso" ]; then
      echo "aviso: $fonte só existe a partir de $piso; usando $piso em vez de $DESDE" >&2
      ano="$piso"
    fi
    eval "${fonte}_DESDE=\$ano"
  done
fi

# ── Plano (--dry-run sai antes de baixar qualquer coisa) ─────────────────────
if [ "$DRY" = 1 ]; then
  echo "PLANO (nada foi baixado nem gravado)"
  echo "  projeto    : $PROJECT_DIR"
  echo "  banco      : $DB ($(sqlite3 "$DB" 'SELECT COUNT(*) FROM companies') empresas hoje)"
  if [ -n "$UNIVERSO" ]; then
    echo "  universo   : $UNIVERSO $([ "$SUBSTITUIR" = 1 ] && echo '(SUBSTITUI o watchlist.csv, com backup)' || echo '(soma ao watchlist.csv)')"
  else
    echo "  universo   : watchlist.csv como está ($(($(wc -l < "$WATCHLIST") - 1)) tickers)"
  fi
  echo "  período    : IPE $IPE_DESDE · VLMO $VLMO_DESDE · FRE $FRE_DESDE · DFP $DFP_DESDE · ITR $ITR_DESDE"
  echo "  blocos     : brutos=$([ "$FAZER_INGEST" = 1 ] && echo sim || echo não)" \
       "· tratamento=$([ "$FAZER_ANALISE" = 1 ] && echo sim || echo não)" \
       "· pdf=$([ "$FAZER_PDF" = 1 ] && echo sim || echo não)"
  echo "  pendentes  : $(sqlite3 "$DB" 'SELECT COUNT(*) FROM ipe_docs WHERE texto_extraido IS NULL AND extracao_falhou = 0') PDFs sem texto"
  echo
  echo "Rode o mesmo comando sem --dry-run para executar."
  exit 0
fi

# ── Universo de cobertura ────────────────────────────────────────────────────
# add_companies.py é aditivo e gera company_catalog.csv sozinho na primeira vez.
if [ -n "$UNIVERSO" ]; then
  if [ "$SUBSTITUIR" = 1 ] && [ -f "$WATCHLIST" ]; then
    BACKUP="$WATCHLIST.bak-$(date +%Y%m%d%H%M%S)"
    cp "$WATCHLIST" "$BACKUP"
    head -1 "$WATCHLIST" > "$WATCHLIST.novo" && mv "$WATCHLIST.novo" "$WATCHLIST"
    log "watchlist.csv zerado; cópia do anterior em $(basename "$BACKUP")"
  fi
  cd "$PROJECT_DIR/scripts/ingest"
  case "$UNIVERSO" in
    ibov)   passo "universo: IBOV";            "$PY" add_companies.py --ibov ;;
    ibrx)   passo "universo: IBRX-100";        "$PY" add_companies.py --ibrx ;;
    todas)  passo "universo: todas B3 ativas"; "$PY" add_companies.py --all ;;
    *)
      ARQ="$UNIVERSO"; [ -f "$ARQ" ] || ARQ="$PROJECT_DIR/$UNIVERSO"
      [ -f "$ARQ" ] || erro "universo '$UNIVERSO' não é ibov/ibrx/todas nem um arquivo existente"
      passo "universo: tickers de $(basename "$ARQ")"
      # Aceita uma coluna 'ticker' (CSV com cabeçalho) ou um ticker por linha.
      # Ignora linhas vazias, comentários com # e o cabeçalho.
      TICKERS=$("$PY" - "$ARQ" <<'EOF'
import csv, re, sys
texto = open(sys.argv[1], encoding="utf-8-sig").read().splitlines()
linhas = [l for l in texto if l.strip() and not l.lstrip().startswith("#")]
achados = []
cab = linhas[0].lower() if linhas else ""
if "ticker" in cab and ("," in cab or ";" in cab):
    delim = ";" if cab.count(";") > cab.count(",") else ","
    for r in csv.DictReader(linhas, delimiter=delim):
        chave = next((k for k in r if k and k.strip().lower() == "ticker"), None)
        if chave and r[chave]:
            achados.append(r[chave])
else:
    if "ticker" in cab and len(cab.split()) == 1:
        linhas = linhas[1:]
    achados = [l.split(",")[0].split(";")[0] for l in linhas]
vistos, saida = set(), []
for t in achados:
    t = re.sub(r"[^A-Z0-9]", "", t.strip().upper())
    if re.fullmatch(r"[A-Z]{4}\d{1,2}", t) and t not in vistos:
        vistos.add(t)
        saida.append(t)
if not saida:
    sys.exit("nenhum ticker válido no arquivo (espera-se algo como PETR4, uma coluna 'ticker' ou um por linha)")
print(" ".join(saida))
EOF
      ) || erro "não consegui ler os tickers de $ARQ"
      N=$(echo "$TICKERS" | wc -w | tr -d ' ')
      log "$N tickers: $(echo "$TICKERS" | cut -c1-90)$([ "${#TICKERS}" -gt 90 ] && echo ' ...')"
      for T in $TICKERS; do "$PY" add_companies.py --ticker "$T" || log "aviso: $T não entrou (fora do catálogo B3?)"; done ;;
  esac
  cd "$PROJECT_DIR"
fi

N_WATCH=$(($(wc -l < "$WATCHLIST") - 1))
log "projeto: $PROJECT_DIR"
log "cobertura: $N_WATCH tickers no watchlist.csv"
log "período: IPE $IPE_DESDE · VLMO $VLMO_DESDE · FRE $FRE_DESDE · DFP $DFP_DESDE · ITR $ITR_DESDE"
[ -n "$UNIVERSO" ] || log "(use --universo ibov para começar do IBOV; --help explica as opções)"

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
    [ "$DEPOIS" -lt "$PEND" ] || { log "lote não avançou; parando (tente com RETRY_FAILED=1 no update_weekly.sh)"; break; }
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
