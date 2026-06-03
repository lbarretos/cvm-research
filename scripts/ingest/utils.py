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

# ── Supabase client ───────────────────────────────────────────────────────────

def get_supabase():
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

# ── Upsert Supabase ───────────────────────────────────────────────────────────

def upsert(sb, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    """Faz upsert em lotes no Supabase, sanitizando NaN antes."""
    rows = _sanitize(rows)
    for i in range(0, len(rows), batch):
        sb.table(table).upsert(rows[i:i + batch], on_conflict=conflict).execute()
    print(f"  {table}: {len(rows)} rows")

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
