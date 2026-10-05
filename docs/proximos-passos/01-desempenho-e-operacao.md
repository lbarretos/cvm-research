# Etapa 1: Desempenho e operação

**Implementada em 2026-10-05**, [PR #29](https://github.com/lbarretos/cvm-research/pull/29). Ver "Implementação" no fim.

## Avaliação atual

| Consulta (uma empresa, banco vivo) | Tempo | Limite do MCP |
|---|---|---|
| `vw_balanco WHERE cnpj=… AND fonte='DFP' LIMIT 5` | **24,8 s** | 20 s: **aborta** |
| `vw_dre WHERE cnpj=… AND fonte='ITR' LIMIT 8` | 14,5 s | passa por pouco |
| `ipe_docs WHERE tipo='Press-release' AND data_entrega >= …` | 5,2 s | sem índice em `tipo` |
| `GROUP BY categoria` em `ipe_docs` | 44 s | aborta |
| FTS `MATCH` | 0,01–0,09 s | ok |

Causas:
1. **As views não recebem o filtro.** O plano de execução de `vw_balanco` calcula a CTE `versao_max` e
   **materializa `vw_plano_contas` para a base inteira** antes de aplicar `cnpj_companhia = ?`. As cinco
   views de DRE e balanço repetem esse padrão.
2. **WAL de 12,5 GB.** Um processo Python de outra sessão (PID 19686, worktree `elastic-williams`, aberto
   desde as 13h22 a ~100% de CPU) mantém uma transação de leitura. Enquanto ela existir, o checkpoint não
   roda. Nada no `update_weekly.sh` faz `wal_checkpoint(TRUNCATE)`.
3. **O texto fica em `ipe_docs`.** São 6,7 bi de caracteres em páginas de overflow na mesma tabela dos
   metadados, com `page_size` de 4096. Uma agregação sem índice precisa ler tudo.
4. **`list_tables()` conta as linhas de cada view**: 46 s em `vw_balanco` e 19 s em `vw_dre`, sem timeout.
   O inventário completo levou cerca de 3 minutos.

## Proposta

| # | Ação |
|---|---|
| 1.1 | Tabela **`filings`** `(cnpj_companhia, fonte, tipo_doc, data_referencia) PK → versao, plano_contas, dt_ini_min, dt_ini_max, n_linhas`, `WITHOUT ROWID`. Gerada ao fim de `ingest_dfp`/`ingest_itr` (ou como primeiro passo do `run_all.py`). O plano é lido da DRE e replicado nos cinco `tipo_doc` do mesmo filing |
| 1.2 | `vw_plano_contas` passa a ler de `filings`. `vw_dre`, `vw_dre_acumulada`, `vw_balanco`, `vw_dre_financeiro` e `vw_dre_seguradora` fazem join em `filings` e `demonstrativos_contabeis` pela chave completa, sem CTE, e usam o índice único `ux_dem_periodo` |
| 1.3 | `PRAGMA wal_checkpoint(TRUNCATE)` no fim do `update_weekly.sh` e do `bootstrap.sh`, com aviso no log se o WAL continuar acima de 1 GB (sinal de leitor pendurado) |
| 1.4 | Índices `ipe_docs(tipo, data_entrega)` e `ipe_docs(categoria, data_entrega)`. A skill manda filtrar por `data_entrega`, e os índices atuais estão em `data_referencia` |
| 1.5 | `list_tables()`: contar só tabelas (ou usar a contagem aproximada de `sqlite_stat1` depois de um `ANALYZE`) e devolver `rows = null` nas views. Timeout em todas as ferramentas, não só em `query` |
| 1.6 | `VACUUM` depois do checkpoint, quando houver ~15 GB livres. Avaliar `page_size = 16384` no mesmo passo (texto longo ocupa menos páginas de overflow) |

## Stress test

Script: [`stress/st1_filings_views.py`](stress/st1_filings_views.py). Roda sobre uma **cópia** com
`demonstrativos_contabeis` (4,75 mi de linhas), `companies`, os índices e as views atuais, e cria
`filings` e as views `_v2`.

**1) Equivalência na base inteira** (`EXCEPT` nos dois sentidos):

| View | Linhas | Só na antiga | Só na nova |
|---|---|---|---|
| `vw_plano_contas` | 7.174 | 0 | 0 |
| `vw_balanco` | 7.174 | 0 | 0 |
| `vw_dre` | 7.174 | 0 | 0 |

As views reescritas devolvem **exatamente** o mesmo resultado, inclusive nos bancos e seguradoras (valores
NULL fora do plano padrão) e na escolha do trimestre isolado (`dt_ini_max`).

**2) Latência por empresa** (consulta típica da skill):

| View | n | p50 | p95 | máx. |
|---|---|---|---|---|
| `vw_balanco` (atual, cópia compactada) | 9 | 2.851 ms | 2.861 ms | 2.871 ms |
| `vw_balanco_v2` | **146** | **3,1 ms** | 3,6 ms | 4,1 ms |
| `vw_dre` (atual, cópia compactada) | 9 | 1.903 ms | 1.921 ms | 1.940 ms |
| `vw_dre_v2` | **146** | **2,5 ms** | 3,9 ms | 6,1 ms |

**3) Carga ampla** (screen de todas as empresas, DFP 2024): `vw_dre_v2` 418 ms contra `vw_dre` 2.285 ms.

**4) Construção de `filings`**: 3,6 s e 35.804 linhas. Cabe no fim de qualquer ingestão.

**Leitura do resultado.** A mesma `vw_balanco` leva 2,9 s na cópia compactada e 24,8 s no banco vivo.
Só compactar e esvaziar o WAL (1.3 + 1.6) já dá ~8×; a reescrita dá outros ~900×. As duas medidas são
independentes e vale fazer as duas.

**Veredito: aprovada.** O screen de 418 ms é o único ponto a acompanhar. Se ele pesar, basta um índice
`filings(fonte, data_referencia)`.

**Não testado:** 1.3 (exige o banco vivo sem o leitor pendurado), 1.4 e 1.5. São mudanças pequenas, e o
efeito delas se mede com a Etapa 2.

## Critério de pronto

- `pytest` verde, incluindo um teste novo de equivalência entre as views antigas e as novas numa fixture.
- Na Etapa 2, nenhuma consulta de demonstrativo acima de 1 s. WAL abaixo de 100 MB depois do job semanal.

## Implementação

| Item | Onde |
|---|---|
| 1.1 `filings` | `schema.sql`, `scripts/ingest/filings.py` (`rebuild_filings`), chamada no fim de `ingest_dfp.py`/`ingest_itr.py` e no início de `run_all.py` |
| 1.2 views | `schema.sql`; migração `scripts/migrations/2026-10-05_filings_views.sql` (cria e preenche `filings`, troca as seis views) |
| 1.3 checkpoint | `checkpoint_wal` em `scripts/update_weekly.sh` e passo "WAL" em `bootstrap.sh`; aviso no log se o `-wal` passar de `WAL_ALERTA_MB` (1024) |
| 1.4 índices | `schema.sql`; migração `scripts/migrations/2026-10-05_ipe_indices.sql` |
| 1.5 MCP | `scripts/mcp/cvm_mcp.py`: `list_tables` devolve `rows = null` nas views; as três ferramentas têm prazo de 20 s |
| 1.6 compactação | `scripts/compactar_banco.sh` (confere espaço e leitores; só mostra o plano sem `--executar`). **Não foi executado**: o banco vivo continua com `page_size` 4096 e sem VACUUM |

`plano_contas` em `filings` é NULL (não `'padrao'`) quando o filing não tem DRE ou 3.01: `vw_plano_contas` continua sem listá-lo,
como antes, e as demais views o tratam como padrão.

**Stress test refeito, agora sobre a base real** (cópia de `demonstrativos_contabeis` e `companies`, views antigas da migração
2026-09-30 contra as novas, `EXCEPT` nos dois sentidos):

| View | Linhas | Só na antiga | Só na nova |
|---|---|---|---|
| `vw_plano_contas` | 7.174 | 0 | 0 |
| `vw_dre` | 7.174 | 0 | 0 |
| `vw_dre_acumulada` | 7.174 | 0 | 0 |
| `vw_dre_financeiro` | 150 | 0 | 0 |
| `vw_dre_seguradora` | 94 | 0 | 0 |
| `vw_balanco` | 7.174 | 0 | 0 |

Latência por empresa nas 146 (cópia, sem WAL): `vw_balanco` p50 5,0 ms, p95 8,1 ms, máx. 12,2 ms; `vw_dre` p50 11,8 ms, p95 16,2 ms,
máx. 24,4 ms; screen de todas as empresas (DFP 2024) 630 ms. `filings` tem 35.804 linhas. No banco vivo, depois de migrar,
`vw_balanco` da WEG (DFP, 3 anos) responde em 0,45 s com a abertura do banco inclusa (eram 24,8 s), e a contagem de Press-releases
por `data_entrega` caiu de 5,2 s para 20 ms. As seis views são testadas em `tests/test_filings.py` contra as definições antigas.

**Ainda aberto:** o `VACUUM` (1.6) e a medição do WAL ao fim de um job semanal completo. Os critérios de pronto que dependem da Etapa 2
(nenhuma consulta de demonstrativo acima de 1 s no conjunto de perguntas) ficam para ela.
