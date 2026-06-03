# CVM Research Database

Base de dados de documentos e eventos de empresas abertas brasileiras, organizada para pesquisa via Claude.

**Fontes:** IPE · VLMO · Recompra de Ações · FRE · DFP/ITR (demonstrativos contábeis)  
**Cobertura:** 56 empresas da watchlist (B3)  
**Atualização:** semanal (IPE/VLMO/FRE/DFP/ITR) e diária (Recompra)  
**Storage:** Supabase PostgreSQL (free tier ~370MB estimado)

---

## Setup

### 1. Supabase

1. Crie um projeto em [supabase.com](https://supabase.com)
2. Vá em **SQL Editor** e rode as migrations em ordem:

```
supabase/migrations/001_companies.sql
supabase/migrations/002_ipe.sql
supabase/migrations/003_vlmo.sql
supabase/migrations/004_recompra.sql
supabase/migrations/005_fre.sql
supabase/migrations/006_rls.sql
supabase/migrations/007_drop_cpf_acionista.sql
supabase/migrations/008_demonstrativos.sql
```

3. Copie a **Project URL**, a **service_role key** e a **anon key** (Settings → API)

### 2. Variáveis de ambiente

```bash
cp .env.example .env
# edite .env com sua URL e chave do Supabase
```

### 3. GitHub Secrets

No repositório: **Settings → Secrets → Actions → New repository secret**

| Secret | Valor |
|--------|-------|
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_KEY` | **service_role key** (necessária para o CI escrever no banco) |

### 4. Primeira carga (manual)

```bash
pip install -r requirements.txt
cd scripts/ingest

python ingest_companies.py      # popula watchlist no Supabase
python ingest_ipe.py            # metadados IPE 2021–hoje (~5 min)
python ingest_vlmo.py           # posição + movimentações (~3 min)
python ingest_recompra.py       # programas de recompra (~30s)
python ingest_fre.py            # capital, acionistas, remuneração (~8 min)
python extract_pdf.py --limite 200   # primeira extração de textos
```

Ou dispare o workflow manualmente: **Actions → Ingest Semanal → Run workflow**

---

## Estrutura do projeto

```
├── watchlist.csv                  # 55 empresas com CNPJ e código CVM
├── CLAUDE.md                      # schema e queries para a skill do Claude
├── requirements.txt
├── .env.example
├── supabase/migrations/           # schema SQL
├── scripts/ingest/
│   ├── utils.py
│   ├── ingest_companies.py
│   ├── ingest_ipe.py
│   ├── ingest_vlmo.py
│   ├── ingest_recompra.py
│   ├── ingest_fre.py
│   └── extract_pdf.py             # extração on-demand de PDFs
└── .github/workflows/
    ├── ingest-weekly.yml          # domingo 08:00 UTC
    └── ingest-daily.yml           # dias úteis 12:00 UTC
```

---

## Uso com Claude Code

Configure o Supabase MCP no Claude Code (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "supabase": {
      "command": "npx",
      "args": [
        "-y", "@supabase/mcp-server-supabase@latest",
        "--supabase-url", "https://SEU-PROJETO.supabase.co",
        "--supabase-key", "SUA-ANON-KEY"
      ]
    }
  }
}
```

> **Importante:** use a **anon key** (não a service_role key) no MCP do Claude. Com o RLS configurado (migration 006), a anon key tem permissão somente de SELECT — leitura segura sem risco de escrita acidental.

Com o MCP ativo, abra Claude Code neste diretório. O `CLAUDE.md` já documenta o schema e os padrões de query — Claude saberá como pesquisar sem instruções adicionais.

**Exemplos de perguntas:**

- *"Resumo das últimas AGOs e AGEs da WEG com o que foi deliberado"*
- *"Fatos relevantes da Embraer no último ano — classifica por tipo de impacto"*
- *"Houve compra ou venda de ações por insiders da Localiza próximo a algum fato relevante em 2024?"*
- *"Compare a remuneração dos diretores de RDOR3 e HAPV3 nos últimos 3 anos"*
- *"Quais programas de recompra estão vigentes no universo de cobertura?"*

---

## Extração de PDFs

Por padrão, o workflow extrai 150 documentos por semana para as empresas da watchlist. Para extrair mais ou para uma empresa específica:

```bash
# todos os pendentes de uma empresa
python scripts/ingest/extract_pdf.py --cnpj 84.429.695/0001-11

# só fatos relevantes, lote maior
python scripts/ingest/extract_pdf.py --categoria "Fato Relevante" --limite 500
```

---

## Monitorar storage

```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS tamanho_db;
```
