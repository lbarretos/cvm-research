import csv
import io
import os
import sys
import time
import zipfile
from pathlib import Path
from dotenv import load_dotenv

import httpx
import pandas as pd

load_dotenv(Path(__file__).parents[2] / ".env")

WATCHLIST_PATH = Path(__file__).parents[2] / "watchlist.csv"

# ── Watchlist ─────────────────────────────────────────────────────────────────

def load_watchlist() -> dict[str, dict]:
    """Retorna dict cnpj -> {ticker, codigo_cvm, nome_cvm, setor}."""
    watchlist = {}
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["cnpj"] == "VERIFICAR":
                continue
            watchlist[row["cnpj"]] = {
                "ticker":      row["ticker"],
                "codigo_cvm":  row["codigo_cvm"],
                "nome_cvm":    row["nome_cvm"],
                "setor":       row["setor"],
                "status_cvm":  row["status_cvm"],
            }
    return watchlist

def watchlist_cnpjs() -> set[str]:
    return set(load_watchlist().keys())

# ── Mapeamento de índice nomeado → colunas (para ON CONFLICT sem CONSTRAINT) ──
# vlmo_mov_uniq é um CREATE UNIQUE INDEX (não uma CONSTRAINT nomeada),
# portanto ON CONFLICT ON CONSTRAINT não funciona — precisamos das colunas.

EXCLUDED_FROM_UPDATE: frozenset = frozenset({'id', 'created_at'})

_INDEX_COLUMNS: dict[str, str] = {
    # nome_index -> colunas_csv para ON CONFLICT (col1,col2,...)
    # NULLS NOT DISTINCT está na definição do índice (migration 009), não aqui.
    "vlmo_mov_uniq": (
        "cnpj_companhia,data_referencia,versao,empresa,"
        "tipo_cargo,tipo_movimentacao,tipo_ativo,caracteristica,"
        "data_movimentacao,quantidade"
    ),
}

# ── Conexão de banco de dados ─────────────────────────────────────────────────

def get_db():
    """Retorna conexão psycopg2 para PostgreSQL local."""
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])

def get_supabase():
    """Retorna cliente Supabase (nuvem) ou conexão psycopg2 (local).

    Modo dual: quando DATABASE_URL estiver no .env, usa psycopg2.
    Quando SUPABASE_URL + SUPABASE_KEY estiverem definidos, usa supabase-py.
    """
    if os.environ.get("DATABASE_URL"):
        return get_db()
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    client = create_client(url, key)
    try:
        client.table("companies").select("cnpj").limit(1).execute()
    except Exception as e:
        if "401" in str(e) or "403" in str(e) or "Unauthorized" in str(e):
            print(f"ERRO DE AUTENTICAÇÃO: chave Supabase inválida — {e}", file=sys.stderr)
            sys.exit(1)
        raise  # re-raise erros de rede ou outros (não autenticação)
    return client

# ── Helpers de conversão de tipo ─────────────────────────────────────────────
# Extraídos de ingest_fre.py — compartilhados por todos os ingestores.

def _date(v):
    """Converte string de data para ISO 8601 ou None se ausente/inválida.

    Tenta ISO 8601 (YYYY-MM-DD) primeiro, depois DD/MM/YYYY (padrão CVM).
    Evita a heurística ambígua do pandas para datas como 03/06/2026.
    """
    if not v or str(v).strip() in ("", "nan"):
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return pd.to_datetime(s, format=fmt).date().isoformat()
        except Exception:
            continue
    return None

def _int(v):
    """Converte string para int ou None se ausente/inválida."""
    try:
        f = float(str(v).replace(",", "."))
        return None if f != f else int(f)  # f != f detecta NaN
    except Exception:
        return None

def _float(v):
    """Converte string para float ou None se ausente/inválida (incluindo string vazia)."""
    try:
        f = float(str(v).replace(",", "."))
        return None if f != f else f
    except Exception:
        return None

def _sanitize(rows: list[dict]) -> list[dict]:
    """Remove float NaN de qualquer campo do dict (Supabase rejeita NaN)."""
    def clean(val):
        if isinstance(val, float) and val != val:
            return None
        return val
    return [{k: clean(v) for k, v in row.items()} for row in rows]

# ── Upsert (Supabase ou psycopg2) ────────────────────────────────────────────

def upsert(sb, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    """Faz upsert em lotes (Supabase ou psycopg2), sanitizando NaN antes."""
    rows = _sanitize(rows)
    if hasattr(sb, 'cursor'):   # psycopg2 connection
        _upsert_pg(sb, table, rows, conflict, batch)
    else:                        # supabase-py client
        for i in range(0, len(rows), batch):
            sb.table(table).upsert(rows[i:i + batch], on_conflict=conflict).execute()
    print(f"  {table}: {len(rows)} rows")

def _upsert_pg(conn, table: str, rows: list[dict], conflict: str, batch: int) -> None:
    """INSERT ... ON CONFLICT DO UPDATE via psycopg2."""
    import psycopg2.extras
    if not rows:
        return
    cols = list(rows[0].keys())

    # Resolve named index → column list; caso contrário usa conflict direto
    conflict_cols = _INDEX_COLUMNS.get(conflict, conflict)
    conflict_clause = f"ON CONFLICT ({conflict_cols})"

    # Deduplica por chave de conflito — psycopg2 rejeita dois DO UPDATE na
    # mesma linha num único comando ("cannot affect row a second time").
    key_cols = [c.strip() for c in conflict_cols.split(",")]
    seen_keys: dict = {}
    for row in rows:
        key = tuple(row.get(c) for c in key_cols)
        seen_keys[key] = row
    rows = list(seen_keys.values())

    update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in EXCLUDED_FROM_UPDATE)
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES %s "
        f"{conflict_clause} DO UPDATE SET {update_set}"
    )
    try:
        with conn.cursor() as cur:
            for i in range(0, len(rows), batch):
                psycopg2.extras.execute_values(
                    cur, sql, [tuple(r[c] for c in cols) for r in rows[i:i + batch]]
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

# ── HTTP com retry ────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 120, retries: int = 3) -> httpx.Response:
    """GET com retry exponencial para erros de rede transitórios.

    Apenas ConnectError e TimeoutException disparam retry — erros HTTP (4xx/5xx)
    propagam imediatamente, pois retry não resolve problema de dados ou autenticação.
    """
    for attempt in range(retries):
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt  # 1s, 2s, 4s, ...
            print(f"  Tentativa {attempt + 1}/{retries} falhou ({exc}). Aguardando {wait}s...")
            time.sleep(wait)
    raise RuntimeError("unreachable")  # satisfaz type checker


# ── Download ZIP CVM (DFP / ITR) ─────────────────────────────────────────────

def download_year(year: int, fonte: str, tipos: list[str]) -> dict[str, pd.DataFrame]:
    """
    Baixa o ZIP anual de DFP ou ITR da CVM e extrai os CSVs consolidados.

    Args:
        year:  Ano de referência (ex: 2024)
        fonte: 'DFP' ou 'ITR'
        tipos: Lista de tipos a extrair (ex: ['BPA', 'BPP', 'DRE', 'DFC_MI', 'DVA'])

    Returns:
        Dict tipo → DataFrame (apenas os tipos encontrados no ZIP).
        Tipos ausentes no ZIP são silenciosamente omitidos — o chamador deve
        verificar com `if tipo not in dfs`.

    Encoding: latin-1 (padrão CVM — igual ao FRE).
    Timeout:  300s (ZIPs de 50-200MB, maior que FRE ~10MB).
    """
    source = fonte.lower()  # 'dfp' ou 'itr'
    url = (
        f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{fonte}/DADOS/"
        f"{source}_cia_aberta_{year}.zip"
    )
    print(f"Baixando {url}...")
    r = _http_get(url, timeout=300)

    dfs: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for tipo in tipos:
            fname = f"{source}_cia_aberta_{tipo}_con_{year}.csv"
            # Proteção contra path traversal (precaução defensiva)
            if ".." in fname or fname.startswith("/"):
                continue
            if fname in z.namelist():
                with z.open(fname) as f:
                    dfs[tipo] = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return dfs
