#!/usr/bin/env bash
# Compacta cvm_research.db (VACUUM) e, se pedido, troca o tamanho de página.
#
#   bash scripts/compactar_banco.sh                       # só mostra o plano (nada é alterado)
#   bash scripts/compactar_banco.sh --executar            # checkpoint + VACUUM
#   bash scripts/compactar_banco.sh --executar --page-size 16384
#
# Por quê: o banco guarda ~6,7 bi de caracteres de texto de PDF em páginas de overflow na mesma
# tabela dos metadados, com page_size 4096. Depois de cargas e do WAL de vários GB, a
# fragmentação deixa até as consultas por empresa ~8x mais lentas (Etapa 1 do roadmap,
# docs/proximos-passos/01-desempenho-e-operacao.md, item 1.6). Páginas de 16 KB gastam menos
# páginas por texto longo.
#
# O VACUUM reescreve o arquivo inteiro: precisa de espaço livre igual ao tamanho do banco (mais
# uma folga) e de NENHUM outro processo com o banco aberto (sessões do Claude, o MCP, o viewer).
# O script confere os dois e recusa se algum falhar. Faça um backup antes se o banco não puder
# ser recarregado.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${CVM_DB_PATH:-$PROJECT_DIR/cvm_research.db}"
EXECUTAR=0; PAGE_SIZE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --executar)  EXECUTAR=1; shift ;;
    --page-size) PAGE_SIZE="${2:?--page-size precisa de um valor}"; shift 2 ;;
    -h|--help)   awk '/^#/ && NR > 1 { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done
case "$PAGE_SIZE" in ""|512|1024|2048|4096|8192|16384|32768|65536) ;; *) echo "ERRO: page-size inválido: $PAGE_SIZE" >&2; exit 2 ;; esac
[ -f "$DB" ] || { echo "ERRO: $DB não existe" >&2; exit 1; }

mb()   { echo $(( $1 / 1048576 )); }
tam()  { stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || echo 0; }
livre_kb=$(df -k "$(dirname "$DB")" | awk 'NR==2 {print $4}')
db_b=$(tam "$DB"); wal_b=$(tam "$DB-wal")
necessario_mb=$(( $(mb "$db_b") + $(mb "$wal_b") + 2048 ))
atual=$(sqlite3 "$DB" "PRAGMA page_size")
leitores=$(lsof -t "$DB" "$DB-wal" 2>/dev/null | sort -u | tr '\n' ' ' || true)

echo "banco         : $DB ($(mb "$db_b") MB, WAL $(mb "$wal_b") MB, page_size $atual)"
echo "espaço livre  : $((livre_kb / 1024)) MB (precisa de ~$necessario_mb MB)"
echo "outros leitores: ${leitores:-nenhum}"
echo "plano         : checkpoint(TRUNCATE) → ${PAGE_SIZE:+page_size=$PAGE_SIZE → }VACUUM"
[ "$EXECUTAR" = 1 ] || { echo; echo "Nada foi alterado. Acrescente --executar para rodar."; exit 0; }

[ $((livre_kb / 1024)) -ge "$necessario_mb" ] || { echo "ERRO: espaço livre insuficiente" >&2; exit 1; }
[ -z "$leitores" ] || { echo "ERRO: processos com o banco aberto (PIDs: $leitores). Feche-os e tente de novo." >&2; exit 1; }

sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
if [ -n "$PAGE_SIZE" ] && [ "$PAGE_SIZE" != "$atual" ]; then
  # page_size só muda fora do WAL, no VACUUM
  sqlite3 "$DB" "PRAGMA journal_mode=DELETE; PRAGMA page_size=$PAGE_SIZE; VACUUM; PRAGMA journal_mode=WAL;" >/dev/null
else
  sqlite3 "$DB" "VACUUM;"
fi
sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
echo "pronto: $(mb "$(tam "$DB")") MB, page_size $(sqlite3 "$DB" 'PRAGMA page_size')"
