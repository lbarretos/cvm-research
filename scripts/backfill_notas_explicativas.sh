#!/bin/bash
# Backfill de notas_explicativas: DFP 2010->hoje, ITR 2018->hoje, todas as empresas da watchlist.
# Roda ano a ano para respeitar o rate limit do portal rad.cvm.gov.br (ver ingest_notas_explicativas.py).
set -uo pipefail

cd "$(dirname "$0")/ingest"
source ../../.venv/bin/activate

ANO_ATUAL=$(date +%Y)

echo "=== DFP: 2010 -> ${ANO_ATUAL} ==="
for ano in $(seq 2010 "$ANO_ATUAL"); do
  echo "--- DFP ${ano} ---"
  python ingest_notas_explicativas.py --fonte DFP --ano "$ano" --limite 2000
done

echo "=== ITR: 2018 -> ${ANO_ATUAL} ==="
for ano in $(seq 2018 "$ANO_ATUAL"); do
  echo "--- ITR ${ano} ---"
  python ingest_notas_explicativas.py --fonte ITR --ano "$ano" --limite 2000
done

echo "=== Backfill concluído ==="
