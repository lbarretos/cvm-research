# TODOS

## ✅ Migração para PostgreSQL local — CONCLUÍDA

**Contexto:** Supabase free tier atingiu 546 MB / 500 MB de limite. Banco migrado para
PostgreSQL 16 local (sem Docker). GitHub Actions desativados. Ingestão passa a ser manual.

**O que foi feito:**
- PostgreSQL 16 instalado via Homebrew e rodando localmente
- Todas as migrations aplicadas em `cvm_research`
- `utils.py` com suporte dual-mode (psycopg2 local ou supabase-py)
- `requirements.txt` com `psycopg2-binary`
- `.env` com `DATABASE_URL=postgresql://localhost/cvm_research`
- Carga inicial completa (~411 MB, 800k+ linhas)
- MCP `postgres-local` configurado via `claude mcp add`
- GitHub Actions `schedule:` removidos (mantidos como `workflow_dispatch` para referência)
- README.md e CLAUDE.md atualizados para arquitetura local

**Próximo passo opcional:** configurar atualização semanal automática via launchd ou Claude routines.

---

## Backlog

- [ ] Configurar atualização automática semanal dos ingestores (launchd ou `/schedule`)
- [ ] Portar `extract_pdf.py` para SQLite — hoje requer Supabase (reescrita de ~100-150 linhas que usam `.select()/.update()` da supabase-py; depende da migração para SQLite)
