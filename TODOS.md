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

## ✅ Expansão de cobertura B3 — CONCLUÍDA

**Contexto:** Cobertura expandida de 54 → 111 empresas usando catálogo automático B3+CVM.

**O que foi feito:**
- `scripts/ingest/catalog.py` — baixa catálogo de 443 empresas ativas da B3+CVM, resolve tickers via IBOV
- `scripts/ingest/add_companies.py` — adiciona empresas ao `watchlist.csv` com modos `--ibov`, `--all`, `--ticker`, `--dry-run`
- 57 empresas do IBOV adicionadas (0 tickers assumidos)
- Histórico estendido: IPE 2015+, DFP/FRE/ITR 2010+, VLMO 2018+
- Banco: ~1.6 GB, 3.4M+ linhas

---

## ✅ Atualização semanal automática — CONCLUÍDA

- `scripts/update_weekly.sh` — roda todos os ingestores + `extract_pdf.py` com lock, log em `logs/` e resumo do banco
- `scripts/install_weekly_launchd.sh` — instala job launchd `com.cvm-research.weekly-update` (segunda 09:00, `--run-now`, `--status`, `--uninstall`)

## Backlog

- [ ] Re-tentar os ~1.680 PDFs prioritários com `extracao_falhou=1` (`extract_pdf.py --retry-failed`) — muitos são digitalizados sem camada de texto
