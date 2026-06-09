#!/bin/bash
# Inicializa o banco SQLite com o schema completo.
# Uso: bash setup.sh [arquivo.db]
# Requer: sqlite3 CLI (instalado por padrão no macOS)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_ARG="${1:-cvm_research.db}"
# Support absolute paths for testing; relative paths are resolved from project root
case "$DB_ARG" in
  /*) DB_PATH="$DB_ARG"; DB_FILE="$(basename "$DB_ARG")" ;;
  *)  DB_FILE="$DB_ARG"; DB_PATH="$SCRIPT_DIR/$DB_FILE" ;;
esac

echo "=== CVM Research — Setup do banco SQLite ==="

if ! command -v sqlite3 &>/dev/null; then
  echo "ERRO: sqlite3 não encontrado."
  echo "No macOS: já vem instalado. No Linux: sudo apt install sqlite3"
  exit 1
fi

if [ -f "$DB_PATH" ]; then
  echo "Banco '$DB_FILE' já existe em $SCRIPT_DIR — pulando criação."
else
  sqlite3 "$DB_PATH" < "$SCRIPT_DIR/schema.sql"
  echo "Banco '$DB_FILE' criado."
fi

echo ""
echo "=== Tabelas criadas ==="
sqlite3 "$DB_PATH" ".tables"

echo ""
echo "✅ Banco pronto. Próximos passos:"
echo "   echo 'DATABASE_URL=sqlite:///$DB_FILE' > .env"
echo "   source .venv/bin/activate"
echo "   cd scripts/ingest && python ingest_companies.py"
echo ""
echo "⚠️  Banco vazio — re-execute todos os ingestores para recarregar dados da CVM:"
echo "   python ingest_companies.py && python ingest_ipe.py && python ingest_vlmo.py"
echo "   python ingest_recompra.py && python ingest_fre.py && python ingest_dfp.py && python ingest_itr.py"
echo ""
echo "⚠️  texto_extraido (texto de PDFs) NÃO é re-ingerido automaticamente."
echo "   Para popular o texto, rode: cd scripts/ingest && python extract_pdf.py"
