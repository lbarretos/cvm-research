# Estado do roadmap e como retomar (2026-10-15)

Documento de passagem para continuar em outra máquina. O que está aqui não está em nenhum outro lugar: o resto vive nos
arquivos de cada etapa e no `README.md` desta pasta.

## Onde as coisas estão

| Item | Situação |
|---|---|
| Etapas 1 a 7 | Na `main` (PRs #29 a #37). Vereditos e números em cada `0N-*.md` e na tabela do [README](README.md) |
| v1 do conjunto de avaliação | Na `main` (PR #38, 2026-10-16): `avaliacao/golden_v1.json` (81 perguntas) e `stress/st2_golden_v1.py`; **baseline não rodada** |
| Banco `cvm_research.db` | **Fora do git** (~19 GB, ignorado). Está só na máquina de origem |
| Etapa 8 (renda fixa) | Na `main` (PR #41). Carga real em 2026-10-30; critérios 1–4 ok; garantia real medida em 366 escrituras (falso positivo 35% → 6%) |
| Skill `cvm-research` | Versionada em `skills/cvm-research/`; a cópia sincronizada em `~/.claude/skills/synced/` é outra, e pode divergir |

## Para continuar em outra máquina

1. `git clone` e `git switch eval-v1` (ou `main`, depois do merge do #38). `bash setup.sh` cria a `.venv`, o schema e o
   symlink `.claude/skills/cvm-research -> ../../skills/cvm-research` (o `.claude/` é ignorado pelo git).
2. **O banco não vem junto.** Duas saídas: copiar o `cvm_research.db` da máquina de origem (checkpoint do WAL antes:
   `sqlite3 cvm_research.db "PRAGMA wal_checkpoint(TRUNCATE)"`), ou montar do zero com `bash bootstrap.sh --universo ibov`
   (horas; as bases divergem nos períodos reapresentados, ver o aviso do `CLAUDE.md`). A base de origem tem 146 empresas.
3. Registrar o MCP: `claude mcp add cvm-research -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"`.
   Ferramentas: `resolve_company`, `query`, `get_financials`, `search_docs`, `read_doc`, `list_tables`, `describe_table`.
4. Um banco montado antes das etapas precisa das migrações, nesta ordem (todas idempotentes ou com aviso):
   `2026-10-05_filings_views.sql`, `2026-10-05_ipe_indices.sql`, `2026-10-06_ipe_chunks.sql` (+ `build_chunks.py`),
   `2026-10-14_template_versao.sql` (+ `template_versions.py`), `2026-10-15_linha_economica.sql`
   (+ `linha_economica.py --full`), `2026-10-16_taxonomia.sql` (+ `taxonomia.py --full`). Banco novo: `bootstrap.sh` já faz tudo.
5. Conferir: `.venv/bin/python -m pytest tests/ -q` (323 passam) e a pergunta de verificação do `INSTALL.md`.
6. Branch protegido: a `main` exige PR. `gh pr merge N --merge`, na ordem quando empilhados.

## Pendências (em ordem de valor)

0. **Etapa 8**: carga real feita (ver `08-renda-fixa.md`). Taxa e cadastro de CRI/CRA vêm do dataset público
   "CRIs e CRAs - Precificação ANBIMA" (data.anbima.com.br → Datasets): o usuário baixa toda semana (formulário) e roda
   `ingest_rf_taxas.py --arquivo X.xls`. A API interna do site exige token e não é usada. Falta: termo dos dois CRAs
   (`ingest_rf_docs.py --codigo X --arquivo termo.pdf`, PDF da aba Documentos); fiança/aval sem gabarito (precisão não medida).
1. **Rodar a baseline do v1** (o #38 já está na `main`): `run_eval.py --golden v1 --rotulo v1-baseline --paralelo 4
   --timeout 600` (~US$ 35–40, ~15 min). Sem ela, o v1 é só um conjunto, não uma régua. A conta já bateu no limite de uso
   no meio de uma execução; se cair, refaça só as ids invalidadas com `--ids` e junte os relatórios.
2. **Etapa 7, regras**: os 14 conceitos de regra revistos nome a nome em 2026-10-30 (`stress/st7_revisao.py`; ver
   `07-taxonomia-canonica.md`): 0 erros nos nomes revistos, D&A × DVA 90,4%. Falta um analista conferir a lista `ERROS`,
   e rodar `st7_revisao.py --listar` depois de cada mudança de regra (nome novo não está revisto).
3. **Etapa 3, tokens**: feita em 2026-10-30 (PR #44): −30% de tokens por pergunta no v0 (projeção com 9 remedidas). Falta
   uma execução completa para confirmar; `num_turns` não serve de medida (conta a injeção da skill).
4. **Etapa 6.4**: feita em 2026-10-30 — o visualizador lê `linha_empresa` (as duas partições discordam em ~0,25% das
   ligações; venceu a fonte única, que respeita `linha_decisao`).
5. **Camada 6 não lê `linha_decisao`** (ver `TODOS.md`): as decisões humanas valem para `linha_empresa`, não para
   `demonstrativos_trimestrais`.
6. **Etapa 7, fora do escopo feito**: modelo supervisionado e fila de revisão (3.b, 3.c), DMPL, demonstrações individuais,
   bancos e seguradoras (DRE de banco sem `versao_template`), safra reapresentada.
7. **Etapa 4, 4.1 e 4.6**: texto separado em `ipe_texto` e embeddings (`sqlite-vec`) não foram feitos.
8. **v1: perguntas conceituais sobre o texto** e documentos longos (proposta da AGO) pedem gabarito escrito à mão.
9. **Skill duplicada**: remover a cópia sincronizada em `~/.claude/skills/synced/` ou mantê-la igual à do repositório.

## Armadilhas que custaram tempo

- `run_eval.py` roda `claude -p` por pergunta; com a API lenta ou no limite de uso, a execução trava ou grava "erro" que não
  é do modelo (`juiz ilegível: You've hit your session limit`). Confira `nota_correcao` antes de concluir regressão.
  O executor mata o grupo de processos no timeout; processos órfãos: `pkill -f "claude -p"`.
- `sed -i` do macOS exige `''` (`sed -i '' ...`); `grep`/glob que não casa derruba um `&&` inteiro no zsh.
- `build_chunks.py`: nunca usar `length(texto_extraido)` (lê os 13 GB) nem `UPDATE` com subconsulta correlacionada sem índice
  (O(N²) com 1,3 mi de trechos); ambos já corrigidos, há teste de regressão.
- O job semanal (launchd) roda do working tree: trocar de branch no meio de uma rodada muda o código que ele executa.
- Um `.backup` do banco leva alguns minutos e 19 GB; confira o espaço antes (`df -h .`).
- Contagens de FR e números reapresentados mudam com a recarga; o `golden_v*.json` guarda `gerado_em`.

## Números de referência (2026-10-15)

| | |
|---|---|
| Banco | 146 empresas, ~19 GB; `ipe_docs` 171.844, `linha_empresa` 2,2 mi, `fato_padronizado` 138 mil, `ipe_chunks` 1,3 mi |
| Testes | 323 passam |
| Avaliação v0 (28) | 27/28, 4,4 chamadas e ~319 mil tokens por pergunta, 0 erros de ferramenta, 0 abortadas |
| Busca por trecho | p95 3 ms; 0 trechos repetidos no top-10; ~6,9 mil chars por pergunta de documento |
| D&A × DVA (Etapa 7) | 89,5% a menos de 2% (84,9% só com a definição total) |
| Linha econômica | 84 s para a base; fragmentação p90: DRE 2,9, BPP 3,5, DFC 3,8 |
