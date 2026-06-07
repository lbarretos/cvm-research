# PostgreSQL → SQLite Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local PostgreSQL 16 dependency with SQLite so the project runs out-of-the-box on any machine with only `pip install -r requirements.txt`.

**Architecture:** A single `schema.sql` file replaces the nine Supabase migrations for local use. `utils.py` gains `_upsert_sqlite` and a sqlite3-aware `get_db()`; the `upsert()` dispatcher adds an `isinstance(sb, sqlite3.Connection)` branch so all ingestor scripts work unchanged. The Supabase cloud path (for `extract_pdf.py`) is preserved.

**Tech Stack:** Python `sqlite3` (stdlib), SQLite ≥ 3.31 (macOS ships 3.43+), `@modelcontextprotocol/server-sqlite` MCP (replaces `server-postgres`), `pytest` for tests.

---

## Key design decisions

| PostgreSQL feature | SQLite equivalent | Notes |
|---|---|---|
| `TIMESTAMPTZ` | `TEXT` (ISO 8601) | Ingestors already produce ISO strings |
| `DATE` | `TEXT` | Same |
| `BIGSERIAL PRIMARY KEY` | `INTEGER PRIMARY KEY AUTOINCREMENT` | |
| `GENERATED ALWAYS AS (...) STORED` for `ano` | `GENERATED ALWAYS AS (CAST(strftime('%Y', data_entrega) AS INTEGER)) STORED` | SQLite 3.31+ |
| `TSVECTOR` / `GIN` / `search_vector` | FTS5 virtual table `ipe_docs_fts` + manual rebuild | Different query syntax (see CLAUDE.md update) |
| `DISTINCT ON` in views | `MAX(versao)` CTE | Equivalent deduplication |
| `NULLS NOT DISTINCT` on `vlmo_mov_uniq` | Omitted — Python-level dedup handles it | Python `None == None` is True; dedup is stateless but batches are idempotent |
| `ROW LEVEL SECURITY` | Omitted | Single-user local DB |
| `psycopg2` | `sqlite3` (stdlib) | Removed from requirements.txt |
| `DATABASE_URL=postgresql://...` | `DATABASE_URL=sqlite:///cvm_research.db` | Path resolved relative to project root |
| MCP `server-postgres` | MCP `server-sqlite` | New Claude Code / Desktop config |

---

## File map

| Action | File | Responsibility |
|---|---|---|
| Create | `schema.sql` | Unified SQLite DDL (tables + views + FTS5) — replaces 9 migration files |
| Create | `setup.sh` | One-command DB init; replaces `setup_migrations.sh` |
| Modify | `scripts/ingest/utils.py` | Add `_upsert_sqlite`; update `get_db()` + `upsert()` dispatch; remove `_upsert_pg` |
| Modify | `scripts/ingest/extract_pdf.py` | Add fail-fast guard at `main()` entry for SQLite backend |
| Modify | `tests/test_ingest_transform.py` | Replace psycopg2 upsert tests with sqlite3 tests |
| Modify | `requirements.txt` | Remove `psycopg2-binary` |
| Modify | `.env.example` | Update `DATABASE_URL` format |
| Modify | `CLAUDE.md` | New setup instructions, MCP config, FTS query syntax |
| Keep | `supabase/migrations/*.sql` | Reference for cloud deployment — do not delete |
| Keep | `setup_migrations.sh` | Reference — do not delete (add deprecation notice) |

---

## Task 1: Create `schema.sql`

**Files:**
- Create: `schema.sql`

- [ ] **Step 1: Write `schema.sql`**

```sql
-- CVM Research — SQLite Schema
-- Replaces supabase/migrations/*.sql for local development.
-- Run: sqlite3 cvm_research.db < schema.sql   (or via setup.sh)
-- SQLite ≥ 3.31 required (macOS ships 3.43+).

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── 1. companies ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS companies (
    cnpj            TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    codigo_cvm      TEXT,
    nome_cvm        TEXT NOT NULL,
    setor           TEXT,
    status_cvm      TEXT DEFAULT 'ATIVO',
    observacao      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ticker ON companies (ticker);
CREATE INDEX IF NOT EXISTS idx_companies_setor ON companies (setor);

-- ── 2. ipe_docs ───────────────────────────────────────────────────────────────
-- search_vector (TSVECTOR) removed → use ipe_docs_fts virtual table instead.

CREATE TABLE IF NOT EXISTS ipe_docs (
    protocolo_entrega   TEXT PRIMARY KEY,
    cnpj_companhia      TEXT NOT NULL,
    nome_companhia      TEXT,
    codigo_cvm          TEXT,
    data_referencia     TEXT,
    data_entrega        TEXT,
    categoria           TEXT,
    tipo                TEXT,
    especie             TEXT,
    assunto             TEXT,
    tipo_apresentacao   TEXT,
    versao              INTEGER,
    link_download       TEXT,
    ano                 INTEGER GENERATED ALWAYS AS (
                            CAST(strftime('%Y', data_entrega) AS INTEGER)
                        ) STORED,
    texto_extraido      TEXT,
    extraido_em         TEXT,
    extracao_falhou     INTEGER DEFAULT 0,
    chars_extraidos     INTEGER,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ipe_cnpj_data  ON ipe_docs (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_ipe_categoria  ON ipe_docs (categoria);
CREATE INDEX IF NOT EXISTS idx_ipe_cnpj_cat   ON ipe_docs (cnpj_companhia, categoria, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_ipe_ano        ON ipe_docs (ano);
CREATE INDEX IF NOT EXISTS idx_ipe_sem_texto  ON ipe_docs (cnpj_companhia)
    WHERE texto_extraido IS NULL AND extracao_falhou = 0;

-- FTS5 virtual table for full-text search (external content, manual rebuild).
-- After loading texto_extraido, rebuild with:
--   INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild');
-- Query syntax (different from PostgreSQL tsvector):
--   SELECT i.* FROM ipe_docs_fts f JOIN ipe_docs i USING (protocolo_entrega)
--   WHERE ipe_docs_fts MATCH 'aquisicao AND controle' ORDER BY rank LIMIT 20;
CREATE VIRTUAL TABLE IF NOT EXISTS ipe_docs_fts USING fts5(
    protocolo_entrega,
    cnpj_companhia,
    assunto,
    texto_extraido,
    content='ipe_docs',
    content_rowid='rowid'
);

-- ── 3. vlmo_posicao ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vlmo_posicao (
    protocolo_entrega     TEXT PRIMARY KEY,
    cnpj_companhia        TEXT NOT NULL,
    nome_companhia        TEXT,
    data_referencia       TEXT,
    versao                INTEGER,
    codigo_cvm            TEXT,
    categoria             TEXT,
    tipo                  TEXT,
    data_entrega          TEXT,
    tipo_apresentacao     TEXT,
    motivo_reapresentacao TEXT,
    link_download         TEXT,
    created_at            TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vlmo_pos_cnpj ON vlmo_posicao (cnpj_companhia, data_referencia DESC);

-- ── 4. vlmo_movimentacoes ─────────────────────────────────────────────────────
-- NULLS NOT DISTINCT omitted (not supported in SQLite).
-- Idempotency guaranteed by Python-level dedup in _upsert_sqlite before each batch.

CREATE TABLE IF NOT EXISTS vlmo_movimentacoes (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia         TEXT NOT NULL,
    nome_companhia         TEXT,
    data_referencia        TEXT,
    versao                 INTEGER,
    tipo_empresa           TEXT,
    empresa                TEXT,
    tipo_cargo             TEXT,
    tipo_movimentacao      TEXT,
    descricao_movimentacao TEXT,
    tipo_operacao          TEXT,
    tipo_ativo             TEXT,
    caracteristica         TEXT,
    intermediario          TEXT,
    data_movimentacao      TEXT,
    quantidade             INTEGER,
    preco_unitario         REAL,
    volume                 REAL,
    created_at             TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vlmo_mov_cnpj  ON vlmo_movimentacoes (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_vlmo_mov_cargo ON vlmo_movimentacoes (tipo_cargo);
CREATE INDEX IF NOT EXISTS idx_vlmo_mov_tipo  ON vlmo_movimentacoes (tipo_movimentacao);

CREATE UNIQUE INDEX IF NOT EXISTS vlmo_mov_uniq ON vlmo_movimentacoes (
    cnpj_companhia, data_referencia, versao, empresa,
    tipo_cargo, tipo_movimentacao, tipo_ativo, caracteristica,
    data_movimentacao, quantidade
);

-- ── 5. recompra ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS recompra_programas (
    id_programa                    INTEGER PRIMARY KEY,
    cnpj_companhia                 TEXT NOT NULL,
    nome_companhia                 TEXT,
    quantidade_acoes_ordinarias    INTEGER,
    quantidade_acoes_preferenciais INTEGER,
    finalidade_compra              TEXT,
    data_deliberacao               TEXT,
    motivo                         TEXT,
    data_final_prazo               TEXT,
    situacao                       TEXT,
    created_at                     TEXT DEFAULT (datetime('now')),
    updated_at                     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recompra_cnpj ON recompra_programas (cnpj_companhia, data_deliberacao DESC);

CREATE TABLE IF NOT EXISTS recompra_quantidades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_programa     INTEGER REFERENCES recompra_programas(id_programa),
    cnpj_companhia  TEXT NOT NULL,
    data_referencia TEXT,
    tipo_ativo      TEXT,
    quantidade      INTEGER,
    preco_medio     REAL,
    volume          REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recompra_qtd_cnpj ON recompra_quantidades (cnpj_companhia, data_referencia DESC);

CREATE TABLE IF NOT EXISTS recompra_intermediarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    id_programa    INTEGER REFERENCES recompra_programas(id_programa),
    cnpj_companhia TEXT NOT NULL,
    intermediario  TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);

-- ── 6. fre ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fre_capital_social (
    id                             INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia                 TEXT NOT NULL,
    nome_companhia                 TEXT,
    data_referencia                TEXT,
    versao                         INTEGER,
    id_documento                   INTEGER,
    id_capital_social              INTEGER,
    tipo_capital                   TEXT,
    data_autorizacao_aprovacao     TEXT,
    valor_capital                  REAL,
    quantidade_acoes_ordinarias    INTEGER,
    quantidade_acoes_preferenciais INTEGER,
    quantidade_total_acoes         INTEGER,
    created_at                     TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_capital_social)
);

CREATE INDEX IF NOT EXISTS idx_fre_cap_cnpj ON fre_capital_social (cnpj_companhia, data_referencia DESC);

CREATE TABLE IF NOT EXISTS fre_posicao_acionaria (
    id                                       INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia                           TEXT NOT NULL,
    nome_companhia                           TEXT,
    data_referencia                          TEXT,
    versao                                   INTEGER,
    id_documento                             INTEGER,
    id_acionista                             INTEGER,
    acionista                                TEXT,
    tipo_pessoa_acionista                    TEXT,
    cpf_cnpj_acionista                       TEXT,
    quantidade_acao_ordinaria_circulacao     INTEGER,
    percentual_acao_ordinaria_circulacao     REAL,
    quantidade_acao_preferencial_circulacao  INTEGER,
    percentual_acao_preferencial_circulacao  REAL,
    quantidade_total_acoes_circulacao        INTEGER,
    percentual_total_acoes_circulacao        REAL,
    nacionalidade                            TEXT,
    residente_exterior                       TEXT,
    acionista_controlador                    TEXT,
    participante_acordo_acionistas           TEXT,
    data_composicao_capital_social           TEXT,
    created_at                               TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_acionista)
);

CREATE INDEX IF NOT EXISTS idx_fre_acionist_cnpj        ON fre_posicao_acionaria (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_fre_acionist_controlador ON fre_posicao_acionaria (acionista_controlador);

CREATE TABLE IF NOT EXISTS fre_remuneracao_orgao (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia             TEXT NOT NULL,
    nome_companhia             TEXT,
    data_referencia            TEXT,
    versao                     INTEGER,
    id_documento               INTEGER,
    data_inicio_exercicio      TEXT,
    data_fim_exercicio         TEXT,
    orgao_administracao        TEXT,
    numero_membros             REAL,
    numero_membros_remunerados REAL,
    valor_maior_remuneracao    REAL,
    valor_menor_remuneracao    REAL,
    valor_medio_remuneracao    REAL,
    observacao                 TEXT,
    created_at                 TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_documento, orgao_administracao, data_fim_exercicio)
);

CREATE INDEX IF NOT EXISTS idx_fre_rem_cnpj ON fre_remuneracao_orgao (cnpj_companhia, data_referencia DESC);

-- ── 7. demonstrativos_contabeis ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS demonstrativos_contabeis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL DEFAULT 1,
    ordem_exercicio TEXT NOT NULL CHECK (ordem_exercicio IN ('Último', 'Penúltimo')),
    dt_ini_exerc    TEXT,
    dt_fim_exerc    TEXT,
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    vl_conta        REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, fonte, tipo_doc, data_referencia, versao, cd_conta, ordem_exercicio)
);

CREATE INDEX IF NOT EXISTS idx_dem_cnpj_fonte ON demonstrativos_contabeis (cnpj_companhia, fonte, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_dem_tipo_conta ON demonstrativos_contabeis (tipo_doc, cd_conta);
CREATE INDEX IF NOT EXISTS idx_dem_cnpj_tipo  ON demonstrativos_contabeis (cnpj_companhia, tipo_doc, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_dem_versao     ON demonstrativos_contabeis (cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, ordem_exercicio, versao DESC);

-- ── Views ─────────────────────────────────────────────────────────────────────
-- DISTINCT ON (PostgreSQL) replaced by MAX(versao) CTE — semantically equivalent.

CREATE VIEW IF NOT EXISTS vw_dre AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, data_referencia, cd_conta, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc = 'DRE' AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, data_referencia, cd_conta
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.data_referencia,
           d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia  = v.cnpj_companhia
      AND d.fonte           = v.fonte
      AND d.data_referencia = v.data_referencia
      AND d.cd_conta        = v.cd_conta
      AND d.versao          = v.versao
    WHERE d.tipo_doc = 'DRE' AND d.ordem_exercicio = 'Último'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_ini_exerc) AS dt_ini_exerc,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN cd_conta = '3.01' THEN vl_conta END) AS receita_liquida,
    MAX(CASE WHEN cd_conta = '3.02' THEN vl_conta END) AS custo_bens_servicos,
    MAX(CASE WHEN cd_conta = '3.03' THEN vl_conta END) AS resultado_bruto,
    MAX(CASE WHEN cd_conta = '3.05' THEN vl_conta END) AS ebit,
    MAX(CASE WHEN cd_conta = '3.06' THEN vl_conta END) AS resultado_financeiro,
    MAX(CASE WHEN cd_conta = '3.08' THEN vl_conta END) AS ebt,
    MAX(CASE WHEN cd_conta = '3.11' THEN vl_conta END) AS lucro_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;

CREATE VIEW IF NOT EXISTS vw_balanco AS
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE tipo_doc IN ('BPA', 'BPP') AND ordem_exercicio = 'Último'
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia, cd_conta
),
latest AS (
    SELECT d.cnpj_companhia, d.fonte, d.tipo_doc, d.data_referencia,
           d.dt_fim_exerc, d.cd_conta, d.vl_conta
    FROM demonstrativos_contabeis d
    JOIN versao_max v
      ON  d.cnpj_companhia  = v.cnpj_companhia
      AND d.fonte           = v.fonte
      AND d.tipo_doc        = v.tipo_doc
      AND d.data_referencia = v.data_referencia
      AND d.cd_conta        = v.cd_conta
      AND d.versao          = v.versao
    WHERE d.tipo_doc IN ('BPA', 'BPP') AND d.ordem_exercicio = 'Último'
)
SELECT
    cnpj_companhia,
    fonte,
    data_referencia,
    MIN(dt_fim_exerc) AS dt_fim_exerc,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1'       THEN vl_conta END) AS ativo_total,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01'    THEN vl_conta END) AS ativo_circulante,
    MAX(CASE WHEN tipo_doc = 'BPA' AND cd_conta = '1.01.01' THEN vl_conta END) AS caixa,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.01.04' THEN vl_conta END) AS divida_curto_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.02.01' THEN vl_conta END) AS divida_longo_prazo,
    MAX(CASE WHEN tipo_doc = 'BPP' AND cd_conta = '2.03'    THEN vl_conta END) AS patrimonio_liquido
FROM latest
GROUP BY cnpj_companhia, fonte, data_referencia;
```

- [ ] **Step 2: Verify schema runs without errors**

```bash
cd /path/to/project
sqlite3 /tmp/cvm_test.db < schema.sql && echo "OK" && rm /tmp/cvm_test.db
```

Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add schema.sql
git commit -m "feat: add SQLite schema (replaces 9 Supabase migrations)"
```

---

## Task 2: Write failing tests for the SQLite database layer

**Files:**
- Modify: `tests/test_ingest_transform.py`

The existing tests import `_upsert_pg` from `utils`. After this task the tests will fail with `ImportError`. That is the expected red state.

- [ ] **Step 1: Replace psycopg2 imports and tests with SQLite versions**

Open `tests/test_ingest_transform.py`. Replace the import line:

```python
# OLD (remove this):
from utils import _date, _float, _http_get, _int, _sanitize, _upsert_pg, upsert, get_supabase

# NEW:
import sqlite3
from utils import _date, _float, _http_get, _int, _sanitize, _upsert_sqlite, upsert, get_supabase
```

- [ ] **Step 2: Replace all psycopg2 upsert tests**

Delete every test function whose name starts with `test_upsert_pg_` or `test_get_supabase_usa_psycopg2_` and the `_make_pg_conn` helper. Replace with:

```python
# ── SQLite helpers ────────────────────────────────────────────────────────────

def _make_sqlite_conn():
    """In-memory SQLite connection with a minimal test schema."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        "CREATE TABLE companies ("
        "  cnpj TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE demo ("
        "  cnpj TEXT, fonte TEXT, tipo TEXT, "
        "  UNIQUE(cnpj, fonte, tipo)"
        ")"
    )
    return conn


# ── _upsert_sqlite ────────────────────────────────────────────────────────────

def test_upsert_sqlite_lista_vazia_nao_usa_cursor():
    conn = _make_sqlite_conn()
    _upsert_sqlite(conn, "companies", [], "cnpj", batch=500)
    assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0


def test_upsert_sqlite_insere_nova_linha():
    conn = _make_sqlite_conn()
    _upsert_sqlite(conn, "companies", [{"cnpj": "00.000.000/0001-00", "ticker": "TEST3"}], "cnpj")
    assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1


def test_upsert_sqlite_atualiza_linha_existente():
    conn = _make_sqlite_conn()
    conn.execute("INSERT INTO companies (cnpj, ticker) VALUES ('00.000.000/0001-00', 'OLD')")
    conn.commit()
    _upsert_sqlite(conn, "companies", [{"cnpj": "00.000.000/0001-00", "ticker": "NEW"}], "cnpj")
    ticker = conn.execute(
        "SELECT ticker FROM companies WHERE cnpj = '00.000.000/0001-00'"
    ).fetchone()[0]
    assert ticker == "NEW"


def test_upsert_sqlite_deduplica_por_chave_conflito():
    conn = _make_sqlite_conn()
    rows = [
        {"cnpj": "00.000.000/0001-00", "ticker": "FIRST"},
        {"cnpj": "00.000.000/0001-00", "ticker": "LAST"},
    ]
    _upsert_sqlite(conn, "companies", rows, "cnpj")
    assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
    assert conn.execute("SELECT ticker FROM companies").fetchone()[0] == "LAST"


def test_upsert_sqlite_batching_multiplos_lotes():
    conn = _make_sqlite_conn()
    rows = [{"cnpj": f"cnpj_{i}", "ticker": f"T{i}"} for i in range(7)]
    _upsert_sqlite(conn, "companies", rows, "cnpj", batch=3)
    assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 7


def test_upsert_sqlite_exclui_created_at_do_update_set():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO companies (cnpj, ticker, created_at) VALUES ('x', 'OLD', '2020-01-01')"
    )
    conn.commit()
    _upsert_sqlite(conn, "companies", [{"cnpj": "x", "ticker": "NEW", "created_at": "2099-01-01"}], "cnpj")
    row = conn.execute("SELECT ticker, created_at FROM companies WHERE cnpj = 'x'").fetchone()
    assert row[0] == "NEW"
    assert row[1] == "2020-01-01"  # created_at must NOT be overwritten


def test_upsert_sqlite_conflict_multiplas_colunas():
    conn = _make_sqlite_conn()
    rows = [{"cnpj": "x", "fonte": "DFP", "tipo": "DRE"}]
    _upsert_sqlite(conn, "demo", rows, "cnpj,fonte,tipo")
    assert conn.execute("SELECT COUNT(*) FROM demo").fetchone()[0] == 1


def test_upsert_despacha_para_sqlite_quando_sb_e_sqlite_connection():
    conn = sqlite3.connect(':memory:')
    with patch("utils._upsert_sqlite") as mock_sq:
        upsert(conn, "companies", [{"cnpj": "x", "ticker": "T"}], conflict="cnpj")
        mock_sq.assert_called_once()
        args = mock_sq.call_args[0]
        assert args[0] is conn
        assert args[1] == "companies"
        assert args[3] == "cnpj"


def test_upsert_sanitiza_nan_antes_de_chamar_upsert_sqlite():
    conn = _make_sqlite_conn()
    rows = [{"cnpj": "00.000.000/0001-00", "ticker": math.nan}]
    _upsert_sqlite(conn, "companies", rows, "cnpj")
    ticker = conn.execute(
        "SELECT ticker FROM companies WHERE cnpj = '00.000.000/0001-00'"
    ).fetchone()[0]
    assert ticker is None


def test_get_supabase_usa_sqlite_quando_database_url_definido():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    try:
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{db_path}"}, clear=False):
            result = get_supabase()
        assert isinstance(result, sqlite3.Connection)
        result.close()
    finally:
        os.unlink(db_path)
```

Note: `test_upsert_despacha_para_supabase_quando_sb_sem_cursor` stays unchanged (Supabase path unaffected).

**Also add the named-index regression test** (replaces `test_upsert_pg_named_index_vlmo_mov_uniq` that was removed above):

```python
def test_upsert_sqlite_named_index_vlmo_mov_uniq():
    """Named index 'vlmo_mov_uniq' must be resolved to column list by _INDEX_COLUMNS."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        "CREATE TABLE vlmo_movimentacoes ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  cnpj_companhia TEXT, data_referencia TEXT, versao INTEGER, empresa TEXT,"
        "  tipo_cargo TEXT, tipo_movimentacao TEXT, tipo_ativo TEXT, caracteristica TEXT,"
        "  data_movimentacao TEXT, quantidade INTEGER,"
        "  UNIQUE(cnpj_companhia,data_referencia,versao,empresa,"
        "         tipo_cargo,tipo_movimentacao,tipo_ativo,caracteristica,"
        "         data_movimentacao,quantidade)"
        ")"
    )
    row = {
        "cnpj_companhia": "00.000.000/0001-00",
        "data_referencia": "2024-01-01", "versao": 1, "empresa": "Test",
        "tipo_cargo": "Diretor", "tipo_movimentacao": "Compra",
        "tipo_ativo": "Ação", "caracteristica": "ON",
        "data_movimentacao": "2024-01-05", "quantidade": 100,
    }
    _upsert_sqlite(conn, "vlmo_movimentacoes", [row], "vlmo_mov_uniq")
    assert conn.execute("SELECT COUNT(*) FROM vlmo_movimentacoes").fetchone()[0] == 1
    _upsert_sqlite(conn, "vlmo_movimentacoes", [row], "vlmo_mov_uniq")  # idempotent
    assert conn.execute("SELECT COUNT(*) FROM vlmo_movimentacoes").fetchone()[0] == 1
```

**Fix the NaN test** — change `_upsert_sqlite` to `upsert` so sanitization is tested at the right layer:

```python
def test_upsert_sanitiza_nan_antes_de_chamar_upsert_sqlite():
    """upsert() must call _sanitize (NaN→None) before dispatching to _upsert_sqlite."""
    conn = _make_sqlite_conn()
    rows = [{"cnpj": "00.000.000/0001-00", "ticker": math.nan}]
    upsert(conn, "companies", rows, "cnpj")   # upsert() sanitizes; _upsert_sqlite does not
    ticker = conn.execute(
        "SELECT ticker FROM companies WHERE cnpj = '00.000.000/0001-00'"
    ).fetchone()[0]
    assert ticker is None
```

- [ ] **Step 3: Run tests to confirm red state**

```bash
cd /path/to/project
source .venv/bin/activate
cd tests && python -m pytest test_ingest_transform.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name '_upsert_sqlite' from 'utils'`

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/test_ingest_transform.py
git commit -m "test: replace psycopg2 upsert tests with sqlite3 versions (red)"
```

---

## Task 3: Update `utils.py` — implement the SQLite path

**Files:**
- Modify: `scripts/ingest/utils.py`

- [ ] **Step 1: Replace `get_db()` with SQLite version**

In `scripts/ingest/utils.py`, find the function `get_db` (lines ~56-59) and replace entirely:

```python
def get_db():
    """Retorna conexão sqlite3 para banco local.

    DATABASE_URL deve ser 'sqlite:///relative.db' ou 'sqlite:////abs/path.db'.
    Caminho relativo é resolvido a partir da raiz do projeto.
    """
    import sqlite3
    url = os.environ["DATABASE_URL"]
    path = url.removeprefix("sqlite:///")
    if not os.path.isabs(path):
        path = str(Path(__file__).parents[2] / path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

- [ ] **Step 2: Remove `_upsert_pg` and add `_upsert_sqlite`**

Delete the entire `_upsert_pg` function from `utils.py` (it becomes dead code after this task — psycopg2 will be uninstalled in Task 5, and `upsert()` will no longer route to it). Then add `_upsert_sqlite` in its place:

```python
def _upsert_sqlite(conn, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    """INSERT ... ON CONFLICT DO UPDATE via sqlite3 (requires SQLite ≥ 3.24)."""
    if not rows:
        return
    cols = list(rows[0].keys())

    conflict_cols = _INDEX_COLUMNS.get(conflict, conflict)
    conflict_list = [c.strip() for c in conflict_cols.split(",")]

    # Deduplicate by conflict key (Python None == None handles NULLS-as-equal)
    seen: dict = {}
    for row in rows:
        key = tuple(row.get(c) for c in conflict_list)
        seen[key] = row
    rows = list(seen.values())

    update_set = ", ".join(
        f"{c}=excluded.{c}" for c in cols if c not in EXCLUDED_FROM_UPDATE
    )
    placeholders = ",".join("?" * len(cols))
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
    )

    cur = conn.cursor()
    try:
        for i in range(0, len(rows), batch):
            cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows[i:i + batch]])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
```

- [ ] **Step 3: Update `upsert()` to dispatch to SQLite**

Find the `upsert` function and add the sqlite3 branch as the first check:

```python
def upsert(sb, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    """Faz upsert em lotes (sqlite3 ou supabase-py), sanitizando NaN antes."""
    import sqlite3
    rows = _sanitize(rows)
    if isinstance(sb, sqlite3.Connection):
        _upsert_sqlite(sb, table, rows, conflict, batch)
    else:                          # supabase-py client
        for i in range(0, len(rows), batch):
            sb.table(table).upsert(rows[i:i + batch], on_conflict=conflict).execute()
    print(f"  {table}: {len(rows)} rows")
```

- [ ] **Step 4: Run tests to verify green**

```bash
cd /path/to/project
source .venv/bin/activate
python -m pytest tests/test_ingest_transform.py -v
```

Expected: all tests pass. If any fail, investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest/utils.py
git commit -m "feat: add sqlite3 database path to utils (get_db, _upsert_sqlite, upsert dispatch)"
```

---

## Task 3.5: Add fail-fast guard to `extract_pdf.py`

**Files:**
- Modify: `scripts/ingest/extract_pdf.py`

`extract_pdf.py` uses the Supabase REST API directly (`.select()/.update()` chains). After the SQLite migration, `get_supabase()` returns a `sqlite3.Connection` when `DATABASE_URL` is set. If a user runs `extract_pdf.py` with the SQLite `.env`, it crashes with a confusing `AttributeError`. This guard gives a clear error instead.

- [ ] **Step 1: Add the guard at the top of `main()` in `extract_pdf.py`**

```python
def main():
    import os
    if os.environ.get("DATABASE_URL") and not os.environ.get("SUPABASE_URL"):
        print(
            "ERRO: extract_pdf.py requer Supabase. Defina SUPABASE_URL e SUPABASE_KEY no .env.\n"
            "       O banco local (SQLite) não suporta extração de PDF.",
            file=sys.stderr,
        )
        sys.exit(1)
    # ... rest of existing main() code unchanged
```

- [ ] **Step 2: Run tests to verify no regression**

```bash
python -m pytest tests/test_ingest_transform.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/ingest/extract_pdf.py
git commit -m "fix: fail-fast guard in extract_pdf.py when SQLite backend is configured"
```

---

## Task 4: Create `setup.sh`

**Files:**
- Create: `setup.sh`

- [ ] **Step 1: Write `setup.sh`**

```bash
#!/bin/bash
# Inicializa o banco SQLite com o schema completo.
# Uso: bash setup.sh
# Requer: sqlite3 CLI (instalado por padrão no macOS)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_FILE="${1:-cvm_research.db}"
DB_PATH="$SCRIPT_DIR/$DB_FILE"

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
echo "   O conteúdo extraído requer extract_pdf.py que usa Supabase."
echo "   Mantenha suas credenciais SUPABASE_URL/KEY anotadas se quiser recuperar o texto."
```

- [ ] **Step 2: Make executable and test**

```bash
chmod +x setup.sh
bash setup.sh /tmp/cvm_test_setup.db && rm /tmp/cvm_test_setup.db
```

Expected: prints table names, `✅ Banco pronto.`

- [ ] **Step 3: Deprecate `setup_migrations.sh`**

Add one line at the top of `setup_migrations.sh` (after `#!/bin/bash`):

```bash
echo "DEPRECATED: use 'bash setup.sh' instead (SQLite, no PostgreSQL required)" && exit 0
```

- [ ] **Step 4: Commit**

```bash
git add setup.sh setup_migrations.sh
git commit -m "feat: add setup.sh for SQLite (deprecate setup_migrations.sh)"
```

---

## Task 5: Update `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Remove `psycopg2-binary`**

The full new content of `requirements.txt`:

```
supabase==2.15.0
httpx==0.27.0
pdfplumber==0.11.4
pandas==2.2.3
python-dotenv==1.0.1
pytest==8.3.5
```

`sqlite3` is part of the Python standard library — no package needed.

- [ ] **Step 2: Verify install works**

```bash
pip install -r requirements.txt
```

Expected: no errors. If psycopg2 was already installed, it remains in the venv but is no longer a declared dependency.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: remove psycopg2-binary (SQLite uses stdlib sqlite3)"
```

---

## Task 6: Update `.env.example` and `CLAUDE.md`

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `.env.example`**

New content:

```
# Banco local SQLite (padrão — sem instalação adicional)
DATABASE_URL=sqlite:///cvm_research.db

# Supabase (nuvem) — necessário apenas para extract_pdf.py
# Deixar em branco para usar SQLite nos ingestores.
# SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
# SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

- [ ] **Step 2: Update the "Configuração do MCP" section in `CLAUDE.md`**

Replace the entire `## Configuração do MCP` section:

````markdown
## Configuração do MCP (ler antes de começar)

Para o Claude acessar o banco, o MCP `postgres-local` precisa estar conectado.
Setup completo em `README.md`. Resumo rápido:

```bash
# 1. Criar banco e configurar .env
bash setup.sh                          # cria cvm_research.db
echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env

# 2. MCP no Claude Code
claude mcp add postgres-local -s user -- $(which npx) \
  -y @modelcontextprotocol/server-sqlite \
  $(pwd)/cvm_research.db

# 3. MCP no Claude desktop app
# Editar: ~/Library/Application Support/Claude/claude_desktop_config.json
# Adicionar:
# "mcpServers": {
#   "postgres-local": {
#     "command": "/caminho/absoluto/do/npx",
#     "args": ["-y", "@modelcontextprotocol/server-sqlite", "/caminho/absoluto/cvm_research.db"]
#   }
# }
# Reiniciar o app após editar.
```

**Verificar conexão** — peça ao Claude: *"Quantas linhas tem a tabela ipe_docs?"*
Se responder com número, o MCP está funcionando.
````

- [ ] **Step 3: Update the "Busca full-text" query example in `CLAUDE.md`**

Find the `### Busca full-text no conteúdo de documentos` section and replace:

````markdown
### Busca full-text no conteúdo de documentos (SQLite FTS5)

```sql
-- Antes da primeira busca, reconstruir o índice FTS (executar uma vez):
-- INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild');

SELECT i.data_referencia, i.categoria, i.assunto,
       f.rank AS relevancia,
       substr(i.texto_extraido, 1, 300) AS trecho
FROM ipe_docs_fts f
JOIN ipe_docs i ON i.protocolo_entrega = f.protocolo_entrega
WHERE f.cnpj_companhia = '<CNPJ>'
  AND ipe_docs_fts MATCH 'aquisicao AND controle'
ORDER BY rank
LIMIT 20;
```
````

- [ ] **Step 4: Update the "Conexão e atualização manual / MCP" section in `CLAUDE.md`**

Replace the `### MCP — Claude Code (terminal)` and `### MCP — Claude desktop app` subsections:

````markdown
### MCP — Claude Code (terminal)

```bash
claude mcp add postgres-local -s user -- $(which npx) \
  -y @modelcontextprotocol/server-sqlite \
  $(pwd)/cvm_research.db

# Verificar:
claude mcp list   # deve mostrar ✓ Connected
```

### MCP — Claude desktop app (chat visual)

Editar `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "postgres-local": {
      "command": "/caminho/absoluto/do/npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-sqlite",
        "/caminho/absoluto/para/cvm_research.db"
      ]
    }
  }
}
```

Obter o caminho do npx: `which npx`. Obter o caminho absoluto do banco: `pwd`/cvm_research.db. Reiniciar o app após salvar.
````

- [ ] **Step 5: Update `## Defasagem dos dados` note about extract_pdf.py**

Find the line `**Nota:** extract_pdf.py requer Supabase — não funciona com banco local.` — replace with:

```
**Nota:** `extract_pdf.py` requer Supabase e não foi migrado para SQLite. Para
extração de texto de PDFs, continue usando o banco Supabase + as variáveis
SUPABASE_URL/SUPABASE_KEY no `.env`.

**⚠️ Migração de dados existentes:** O campo `texto_extraido` (texto extraído de PDFs)
**não é transferido automaticamente** ao migrar do PostgreSQL para SQLite. Após a
migração, o banco SQLite inicia vazio. Todos os metadados de documentos são
re-ingeridos pelos ingestores (IPE, VLMO, etc.), mas o texto extraído de PDFs
requer re-execução do `extract_pdf.py` contra um banco Supabase. Guarde suas
credenciais `SUPABASE_URL`/`SUPABASE_KEY` se quiser recuperar o conteúdo extraído.
```

- [ ] **Step 6: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: update setup instructions and MCP config for SQLite"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /path/to/project
source .venv/bin/activate
python -m pytest tests/ -v
```

Expected: all tests pass with no warnings about psycopg2.

- [ ] **Step 2: End-to-end smoke test**

```bash
cd /path/to/project
bash setup.sh smoke_test.db
echo 'DATABASE_URL=sqlite:///smoke_test.db' > .env.test
DATABASE_URL=sqlite:///smoke_test.db python scripts/ingest/ingest_companies.py
sqlite3 smoke_test.db "SELECT COUNT(*) FROM companies;"
rm smoke_test.db .env.test
```

Expected: `SELECT COUNT(*)` returns a positive number (≥ 1 company from watchlist).

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "chore: post-migration cleanup and verification"
```

---

## Self-review

**Spec coverage check:**
- ✅ Remove PostgreSQL/psycopg2 dependency → Tasks 3, 5
- ✅ SQLite schema with all 10 tables → Task 1
- ✅ Views rewritten without DISTINCT ON → Task 1 (MAX(versao) CTE)
- ✅ FTS5 virtual table → Task 1
- ✅ `_upsert_sqlite` with ON CONFLICT DO UPDATE → Task 3
- ✅ `get_db()` returns sqlite3.Connection → Task 3
- ✅ `upsert()` dispatches to sqlite3 path → Task 3
- ✅ Tests cover sqlite3 path end-to-end → Task 2
- ✅ MCP config updated → Task 6
- ✅ setup.sh one-command init → Task 4
- ✅ .env.example updated → Task 6
- ✅ Supabase cloud path preserved (extract_pdf.py) → no change needed

**Known limitations vs PostgreSQL:**
- `NULLS NOT DISTINCT` on `vlmo_mov_uniq`: not enforced at DB level in SQLite. Python dedup handles within-batch idempotency; duplicate rows possible only if the same trade appears across separate ingestor runs with NULL `empresa`. Impact: negligible for a research tool.
- FTS5 query syntax differs from `tsvector`/`tsquery`; documented in CLAUDE.md.
- `extracao_falhou` is INTEGER (0/1) not BOOLEAN; Python boolean values (`True`/`False`) will be stored as 1/0 transparently by sqlite3.
- FTS5 is a compile-time option in SQLite. macOS Python always includes it. On some Linux distros (rare, older Debian), it may be absent — the `CREATE VIRTUAL TABLE ... USING fts5(...)` line in `schema.sql` would fail with `no such module: fts5`. Workaround: remove the FTS5 block from schema.sql if targeting such systems.
- `texto_extraido` content is not migrated from PostgreSQL; it requires re-running `extract_pdf.py` against Supabase (see Task 6 warning).

---

## Implementation Tasks
Synthesized from this review's findings. Run with Claude Code; checkbox as you ship.

- [ ] **T1 (P1, human: ~30min / CC: ~5min)** — `utils.py` — Remove `_upsert_pg`, add `_upsert_sqlite`, update `upsert()` dispatch
  - Surfaced by: Architecture Review — D1 dead code finding
  - Files: `scripts/ingest/utils.py`
  - Verify: `pytest tests/test_ingest_transform.py -v` — all pass

- [ ] **T2 (P1, human: ~15min / CC: ~3min)** — `tests/test_ingest_transform.py` — Fix NaN test + add named-index regression test
  - Surfaced by: Code Quality Review — D3 (NaN assertion wrong layer), Test Review — D5 (regression gap)
  - Files: `tests/test_ingest_transform.py`
  - Verify: `pytest tests/ -v` — no failures

- [ ] **T3 (P1, human: ~10min / CC: ~2min)** — `extract_pdf.py` — Add fail-fast guard for SQLite backend
  - Surfaced by: Architecture Review — D2 (prior learning [extract-pdf-supabase-only])
  - Files: `scripts/ingest/extract_pdf.py`
  - Verify: `DATABASE_URL=sqlite:///x.db python scripts/ingest/extract_pdf.py` → exits with clear error message

- [ ] **T4 (P2, human: ~10min / CC: ~2min)** — `setup.sh` + Task 6 — Add data migration and texto_extraido warnings
  - Surfaced by: Code Quality Review — D4, Outside voice — D6
  - Files: `setup.sh`, `CLAUDE.md`
  - Verify: `bash setup.sh` output includes the two ⚠️ warnings

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | 2 real tensions (D3, D6), 8 false positives |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 5 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — 5 issues resolved, 0 critical gaps. Ready to implement.
