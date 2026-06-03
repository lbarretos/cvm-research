# TODOS

## [SETUP MANUAL PENDENTE] PostgreSQL local — sem Docker, sem Supabase

**Contexto:** o banco na nuvem (Supabase free tier) atingiu 546 MB / 500 MB de limite.
A alternativa é rodar PostgreSQL direto no Mac (sem Docker) e conectar o Claude via MCP.
Os GitHub Actions continuam apontando para o Supabase na nuvem para ingestão automática.
O uso local é só para pesquisa via Claude Code.

**Código já implementado (passos 3, 4, 5, 8). Passos 1, 2, 6, 7 são setup manual.**

### Passo 1 — Instalar e configurar PostgreSQL local

```bash
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
createdb cvm_research
```

### Passo 2 — Rodar as migrations

Executar em ordem no banco local:

```bash
psql cvm_research < supabase/migrations/001_companies.sql
psql cvm_research < supabase/migrations/002_ipe.sql
psql cvm_research < supabase/migrations/003_vlmo.sql
psql cvm_research < supabase/migrations/004_recompra.sql
psql cvm_research < supabase/migrations/005_fre.sql
# 006_rls.sql pula — RLS não é necessário para uso local
psql cvm_research < supabase/migrations/007_drop_cpf_acionista.sql
psql cvm_research < supabase/migrations/008_demonstrativos.sql
psql cvm_research < supabase/migrations/009_vlmo_mov_uniq.sql
```

Obs: as migrations usam `CREATE TABLE IF NOT EXISTS` — rodam limpo.

### ✅ Passo 3 — Adicionar suporte a PostgreSQL direto em utils.py (FEITO)

Hoje o `utils.py` usa `supabase-py` (REST API). Para PostgreSQL local, precisa de
`psycopg2` com INSERT ... ON CONFLICT.

**Estratégia dual-mode:** quando `DATABASE_URL` estiver no `.env`, usa psycopg2.
Quando `SUPABASE_URL` + `SUPABASE_KEY` estiverem, usa supabase-py (comportamento atual).
Os ingestores não precisam mudar — só `get_supabase()` e `upsert()` em utils.py.

**Mudanças em `utils.py`:**

```python
# Adicionar ao .env.example:
# DATABASE_URL=postgresql://localhost/cvm_research

def get_db():
    """Retorna conexão psycopg2 para PostgreSQL local."""
    import psycopg2, psycopg2.extras
    return psycopg2.connect(os.environ["DATABASE_URL"])

def get_supabase():
    """Retorna cliente Supabase (nuvem) ou conexão psycopg2 (local)."""
    if os.environ.get("DATABASE_URL"):
        return get_db()          # retorna conexão psycopg2
    # ... código atual com supabase-py
```

A função `upsert()` precisa detectar o tipo do cliente e usar SQL nativo quando for psycopg2:

```python
def upsert(sb, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    rows = _sanitize(rows)
    if hasattr(sb, 'cursor'):   # psycopg2 connection
        _upsert_pg(sb, table, rows, conflict, batch)
    else:                        # supabase-py client
        for i in range(0, len(rows), batch):
            sb.table(table).upsert(rows[i:i+batch], on_conflict=conflict).execute()
        print(f"  {table}: {len(rows)} rows")

def _upsert_pg(conn, table: str, rows: list[dict], conflict: str, batch: int) -> None:
    import psycopg2.extras
    if not rows:
        return
    cols = list(rows[0].keys())
    # conflict pode ser nome de coluna ou de constraint
    conflict_clause = f"ON CONFLICT ON CONSTRAINT {conflict}" \
        if not conflict.isidentifier() or '_uniq' in conflict or conflict == 'vlmo_mov_uniq' \
        else f"ON CONFLICT ({conflict})"
    update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ('id', 'created_at'))
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES %s "
        f"{conflict_clause} DO UPDATE SET {update_set}"
    )
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch):
            psycopg2.extras.execute_values(cur, sql, [tuple(r[c] for c in cols) for r in rows[i:i+batch]])
    conn.commit()
    print(f"  {table}: {len(rows)} rows")
```

**Nota sobre vlmo_posicao:** usa `conflict="protocolo_entrega"` (coluna, não constraint).
**Nota sobre vlmo_movimentacoes:** usa `conflict="vlmo_mov_uniq"` (constraint).
**Nota sobre demonstrativos_contabeis:** sem nome de constraint — usar coluna UNIQUE implícita ou
criar constraint nomeada. Checar com `\d demonstrativos_contabeis` no psql.

### ✅ Passo 4 — Adicionar psycopg2 ao requirements.txt (FEITO)

```
psycopg2-binary==2.9.10
```

Usar `psycopg2-binary` (sem compilação C). Não remover `supabase` — GitHub Actions ainda usa.

### ✅ Passo 5 — Criar .env local para uso com psycopg2 (FEITO — .env.example atualizado)

```bash
# .env (não commitado)
DATABASE_URL=postgresql://localhost/cvm_research
```

Deixar `SUPABASE_URL` e `SUPABASE_KEY` em branco ou comentado no `.env` local
para forçar o modo psycopg2.

### Passo 6 — Carga inicial dos dados

Rodar os ingestores localmente na ordem correta:

```bash
cd scripts/ingest
python ingest_companies.py
python ingest_ipe.py           # ~5 min (metadados, sem PDFs)
python ingest_vlmo.py          # ~3 min
python ingest_recompra.py      # ~30s
python ingest_fre.py           # ~8 min
python ingest_dfp.py           # ~10 min (2021–2026)
python ingest_itr.py           # ~15 min (2021–2026)
# extract_pdf.py: opcional, pesado — pula na primeira carga
```

### Passo 7 — Configurar MCP do Claude para PostgreSQL local

Editar `~/.claude/settings.json` (ou settings.local.json):

```json
{
  "mcpServers": {
    "postgres-local": {
      "command": "npx",
      "args": [
        "-y", "@modelcontextprotocol/server-postgres",
        "postgresql://localhost/cvm_research"
      ]
    }
  }
}
```

Validar que funciona:
```bash
npx -y @modelcontextprotocol/server-postgres postgresql://localhost/cvm_research
```

### ✅ Passo 8 — Atualizar CLAUDE.md para uso local (FEITO)

Adicionar seção explicando como conectar via MCP local vs. nuvem.

---

## O que NÃO muda

- GitHub Actions (`ingest-daily.yml`, `ingest-weekly.yml`) continuam apontando para Supabase nuvem
- As migrations SQL são idênticas (PostgreSQL puro, sem extensão Supabase específica)
- `extract_pdf.py` funciona igual (usa requests + supabase só para escrever)
- Pesquisa via Claude Code usa o MCP local — mais rápido, sem custo, sem limite

---

## Skill para implementar

Abrir novo chat no diretório do projeto e rodar:

```
/ship
```

O `/ship` vai:
1. Revisar o diff planejado acima
2. Implementar as mudanças em `utils.py` e `requirements.txt`
3. Rodar os testes
4. Criar PR

**Contexto para o novo chat:** mostrar este TODOS.md e dizer
"implemente o item de PostgreSQL local — opção B sem Docker".
