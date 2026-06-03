# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras, organizada para pesquisa via Claude Code.

**Fontes:** IPE · VLMO · Recompra de Ações · FRE · DFP/ITR  
**Cobertura:** 56 empresas da watchlist (B3)  
**Banco:** PostgreSQL 16 local (sem Docker, sem cloud)  
**Tamanho:** ~411 MB · 800k+ linhas  
**Atualização:** manual via scripts de ingestão

---

## Setup (primeira vez)

### 1. Instalar PostgreSQL 16

```bash
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 2. Criar banco e rodar migrations

```bash
createdb cvm_research

psql cvm_research < supabase/migrations/001_companies.sql
psql cvm_research < supabase/migrations/002_ipe.sql
psql cvm_research < supabase/migrations/003_vlmo.sql
psql cvm_research < supabase/migrations/004_recompra.sql
psql cvm_research < supabase/migrations/005_fre.sql
# 006_rls.sql pula — RLS não é necessário localmente
psql cvm_research < supabase/migrations/007_drop_cpf_acionista.sql
psql cvm_research < supabase/migrations/008_demonstrativos.sql
psql cvm_research < supabase/migrations/009_vlmo_mov_uniq.sql
```

### 3. Configurar ambiente Python

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Criar `.env` na raiz do projeto:

```bash
DATABASE_URL=postgresql://localhost/cvm_research
```

### 4. Carga inicial dos dados (~30 min no total)

```bash
cd scripts/ingest

python ingest_companies.py       # watchlist (~5s)
python ingest_ipe.py             # metadados IPE 2021–hoje (~5 min)
python ingest_vlmo.py            # insider trading (~3 min)
python ingest_recompra.py        # programas de recompra (~30s)
python ingest_fre.py             # capital, acionistas, remuneração (~8 min)
python ingest_dfp.py --historico # demonstrativos anuais 2021–hoje (~10 min)
python ingest_itr.py             # trimestral do ano corrente (~3 min)
```

### 5. Configurar MCP do Claude Code

```bash
claude mcp add postgres-local -s user -- \
  ~/.fnm/node-versions/v24.14.0/installation/bin/npx \
  -y @modelcontextprotocol/server-postgres \
  postgresql://localhost/cvm_research
```

> Ajuste o caminho do `npx` para o seu ambiente (`which npx`).

---

## Atualização manual

Rodar periodicamente para manter a base em dia:

```bash
cd scripts/ingest
source ../../.venv/bin/activate    # ou .venv/bin/activate no projeto

# Semanalmente
python ingest_ipe.py
python ingest_vlmo.py
python ingest_recompra.py
python ingest_fre.py
python ingest_dfp.py
python ingest_itr.py

# Trimestral (reprocessa toda a série)
python ingest_dfp.py --historico
```

---

## Uso com Claude Code

Com o MCP `postgres-local` conectado, abra Claude Code neste diretório. O `CLAUDE.md` documenta o schema completo e os padrões de query.

**Exemplos de perguntas:**

- *"Resumo das últimas AGOs e AGEs da WEG com o que foi deliberado"*
- *"Fatos relevantes da Embraer no último ano — classifica por tipo de impacto"*
- *"Houve compra ou venda de ações por insiders da Localiza próximo a algum fato relevante em 2024?"*
- *"Compare a remuneração dos diretores de RDOR3 e HAPV3 nos últimos 3 anos"*
- *"Quais programas de recompra estão vigentes no universo de cobertura?"*

---

## Estrutura do projeto

```
├── watchlist.csv                  # 56 empresas com CNPJ e código CVM
├── CLAUDE.md                      # schema e queries para o Claude
├── requirements.txt
├── .env                           # DATABASE_URL (não commitado)
├── .env.example
├── supabase/migrations/           # schema SQL (usado para setup local)
├── scripts/ingest/
│   ├── utils.py                   # get_supabase() / _upsert_pg()
│   ├── ingest_companies.py
│   ├── ingest_ipe.py
│   ├── ingest_vlmo.py
│   ├── ingest_recompra.py
│   ├── ingest_fre.py
│   ├── ingest_dfp.py
│   ├── ingest_itr.py
│   └── extract_pdf.py             # extração on-demand de PDFs (requer Supabase)
└── .github/workflows/             # desativados — ingestão é manual
```

---

## Monitorar o banco

```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS tamanho_db;

SELECT relname AS tabela, n_live_tup AS linhas
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;
```
