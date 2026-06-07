#!/bin/bash
# DEPRECATED: use 'bash setup.sh' instead (SQLite, sem PostgreSQL necessário)
echo "DEPRECATED: use 'bash setup.sh' instead (SQLite, no PostgreSQL required)" && exit 0
# Cria o banco cvm_research e roda todas as migrations em ordem.
# Uso: bash setup_migrations.sh

set -e

DB="cvm_research"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== CVM Research — Setup do banco ==="

# Verificar PostgreSQL
if ! command -v psql &>/dev/null; then
  echo "ERRO: psql não encontrado."
  echo "Instale: brew install postgresql@16 && brew services start postgresql@16"
  echo "Depois: echo 'export PATH=\"/opt/homebrew/opt/postgresql@16/bin:\$PATH\"' >> ~/.zshrc"
  exit 1
fi

# Verificar serviço
if ! psql -l &>/dev/null; then
  echo "ERRO: PostgreSQL não está rodando."
  echo "Execute: brew services start postgresql@16"
  exit 1
fi

# Criar banco (ignora se já existe)
if psql -l | grep -q "$DB"; then
  echo "Banco '$DB' já existe — pulando criação."
else
  createdb "$DB"
  echo "Banco '$DB' criado."
fi

# Rodar migrations em ordem (pula 006_rls.sql — não necessário localmente)
MIGRATIONS=(
  "supabase/migrations/001_companies.sql"
  "supabase/migrations/002_ipe.sql"
  "supabase/migrations/003_vlmo.sql"
  "supabase/migrations/004_recompra.sql"
  "supabase/migrations/005_fre.sql"
  "supabase/migrations/007_drop_cpf_acionista.sql"
  "supabase/migrations/008_demonstrativos.sql"
  "supabase/migrations/009_vlmo_mov_uniq.sql"
)

for f in "${MIGRATIONS[@]}"; do
  echo -n "  $f ... "
  psql "$DB" < "$SCRIPT_DIR/$f" 2>&1 | grep -E "^ERROR" || echo "ok"
done

echo ""
echo "=== Tabelas criadas ==="
psql "$DB" -c "\dt" 2>/dev/null | grep "public"

echo ""
echo "✅ Banco pronto. Próximo passo: criar o .env e rodar os ingestores."
echo "   echo 'DATABASE_URL=postgresql://localhost/$DB' > .env"
