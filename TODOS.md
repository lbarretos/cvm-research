# TODOS

## ✅ Migração para SQLite local — CONCLUÍDA

**Contexto:** Projeto migrado de PostgreSQL/Supabase para SQLite local sem dependências externas.
Banco: `cvm_research.db` · Schema: `schema.sql` · MCP: `mcp-server-sqlite`.

**O que foi feito:**
- SQLite substituiu PostgreSQL e Supabase em todos os ingestores
- `utils.py` simplificado: apenas `get_db()` (sem modo dual)
- `extract_pdf.py` migrado para SQLite nativo
- `supabase` removido do `requirements.txt`
- `supabase/migrations/` e scripts de migração antigos removidos
- GitHub Actions atualizados para usar `DATABASE_URL` (sem `SUPABASE_URL`/`SUPABASE_KEY`)
- README.md e CLAUDE.md atualizados

---

## Backlog

- [ ] Configurar atualização automática semanal dos ingestores (launchd ou `/schedule`)
