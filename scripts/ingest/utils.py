import csv
import io
import os
import re
import sqlite3
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
# Definição do índice está em schema.sql.

EXCLUDED_FROM_UPDATE: frozenset = frozenset({'id', 'created_at'})

_INDEX_COLUMNS: dict[str, str] = {
    # nome_index -> alvo do ON CONFLICT (col1,col2,... ou expressões do índice único)
    # vlmo_mov_uniq em schema.sql — índice de expressão porque data_movimentacao é
    # NULL em 'Saldo Inicial' (e tipo_cargo/caracteristica às vezes): numa UNIQUE
    # comum cada recarga duplicava essas linhas. O alvo tem que repetir as
    # expressões do índice exatamente como estão lá.
    "vlmo_mov_uniq": (
        "cnpj_companhia,IFNULL(data_referencia,''),IFNULL(versao,''),IFNULL(empresa,''),"
        "IFNULL(tipo_cargo,''),IFNULL(tipo_movimentacao,''),IFNULL(tipo_ativo,''),"
        "IFNULL(caracteristica,''),IFNULL(data_movimentacao,''),IFNULL(quantidade,'')"
    ),
    # ux_dem_periodo em schema.sql — índice de expressão porque dt_ini_exerc é
    # NULL em BPA/BPP e NULLs não conflitam entre si numa UNIQUE comum.
    "dem_contabeis_uniq": (
        "cnpj_companhia,fonte,tipo_doc,data_referencia,versao,cd_conta,ordem_exercicio,"
        "COALESCE(dt_ini_exerc,'')"
    ),
}

# Quando o alvo do conflito tem expressões, a deduplicação em Python precisa
# das colunas puras (None == None já trata o NULL como igual).
_DEDUP_COLUMNS: dict[str, str] = {
    "vlmo_mov_uniq": (
        "cnpj_companhia,data_referencia,versao,empresa,"
        "tipo_cargo,tipo_movimentacao,tipo_ativo,caracteristica,"
        "data_movimentacao,quantidade"
    ),
    "dem_contabeis_uniq": (
        "cnpj_companhia,fonte,tipo_doc,data_referencia,versao,cd_conta,ordem_exercicio,dt_ini_exerc"
    ),
}

# ── Conexão de banco de dados ─────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Retorna conexão sqlite3 para banco local.

    DATABASE_URL deve ser 'sqlite:///relative.db' ou 'sqlite:////abs/path.db'.
    Caminho relativo é resolvido a partir da raiz do projeto.
    """
    url = os.environ["DATABASE_URL"]
    if not url.startswith("sqlite:///"):
        raise ValueError(
            f"DATABASE_URL deve começar com 'sqlite:///' — recebido: {url!r}\n"
            "Exemplo: DATABASE_URL=sqlite:///cvm_research.db"
        )
    path = url.removeprefix("sqlite:///")
    if not os.path.isabs(path):
        path = str(Path(__file__).parents[2] / path)
    # timeout: quanto esperar pelo lock de escrita de outro processo antes de "database is locked".
    # O padrão de 5 s derrubou o job semanal de 30/09/2026 (migração e run_all rodando em paralelo).
    conn = sqlite3.connect(path, timeout=300)
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if mode != "wal":
        print(f"AVISO: journal_mode=WAL não ativo (modo atual: {mode!r}). "
              "Verifique se o banco está em rede/OneDrive.", file=sys.stderr)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

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
    """Remove float NaN de qualquer campo do dict (SQLite e pandas produzem NaN em campos vazios)."""
    def clean(val):
        if isinstance(val, float) and val != val:
            return None
        return val
    return [{k: clean(v) for k, v in row.items()} for row in rows]

# ── Escala de DFP/ITR ────────────────────────────────────────────────────────

SCALE = {"MIL": 1000, "UNIDADE": 1}

# Lucro por ação (DRE 3.99 e descendentes) é publicado em R$/ação qualquer que
# seja ESCALA_MOEDA do documento: multiplicar por 1000 dá LPA de 8.540 na Petrobras.
_SEM_ESCALA_PREFIX = "3.99"


def vl_escalado(vl_conta, escala: str, cd_conta: str):
    """VL_CONTA do CSV da CVM → R$. None se vazio; ValueError se a escala for desconhecida."""
    if escala not in SCALE:
        raise ValueError(f"Escala desconhecida: {escala!r}")
    vl = _float(vl_conta)
    if vl is None:
        return None
    if str(cd_conta or "").startswith(_SEM_ESCALA_PREFIX):
        return vl
    return vl * SCALE[escala]

# ── Upsert ───────────────────────────────────────────────────────────────────

def upsert(conn: sqlite3.Connection, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    """Faz upsert em lotes via sqlite3, sanitizando NaN antes."""
    rows = _sanitize(rows)
    _upsert_sqlite(conn, table, rows, conflict, batch)
    print(f"  {table}: {len(rows)} rows")

def _upsert_sqlite(conn, table: str, rows: list[dict], conflict: str, batch: int = 500) -> None:
    """INSERT ... ON CONFLICT DO UPDATE via sqlite3 (requer SQLite ≥ 3.24)."""
    if not rows:
        return
    cols = list(rows[0].keys())

    conflict_cols = _INDEX_COLUMNS.get(conflict, conflict)
    dedup_cols = _DEDUP_COLUMNS.get(conflict, conflict_cols)
    conflict_list = [c.strip() for c in dedup_cols.split(",")]

    # Deduplica por chave de conflito (Python None == None trata NULLs como iguais)
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

# ── HTTP com retry ────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 120, retries: int = 6) -> httpx.Response:
    """GET com retry exponencial para erros de rede transitórios.

    Apenas ConnectError e TimeoutException disparam retry — erros HTTP (4xx/5xx)
    propagam imediatamente, pois retry não resolve problema de dados ou autenticação.
    Esperas de 4s, 8s, 16s, 32s e 60s (teto): com o default de 6 tentativas, a rede
    tem ~2 min para voltar — o DNS logo após o Mac acordar leva mais que segundos.
    """
    for attempt in range(retries):
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if attempt == retries - 1:
                raise
            wait = min(4 * 2 ** attempt, 60)
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


def fetch_doc_metadata(year: int, fonte: str) -> pd.DataFrame:
    """
    Baixa o CSV principal (não os _con_/_ind_) do ZIP anual de DFP/ITR.

    Esse CSV traz ID_DOC (= NumeroSequencialDocumento) e LINK_DOC por
    (CNPJ_CIA, DT_REFER, VERSAO) — é o único ponto de acesso ao pacote
    ZIP completo do documento, que contém o PDF com as Notas Explicativas.
    Os CSVs _con_/_ind_ (consumidos por download_year) não têm essa
    informação; só o CSV principal do ZIP tem.

    Ver ingest_notas_explicativas.py para o consumidor.

    Colunas retornadas: CNPJ_CIA, DT_REFER, VERSAO, ID_DOC (todas como string,
    dtype=str — conversão para int fica a cargo do chamador).
    """
    source = fonte.lower()
    url = (
        f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{fonte}/DADOS/"
        f"{source}_cia_aberta_{year}.zip"
    )
    r = _http_get(url, timeout=300)
    fname = f"{source}_cia_aberta_{year}.csv"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(fname) as f:
            df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return df[["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"]]


# ── Reparo de texto extraído de PDF ──────────────────────────────────────────
# Dois defeitos do pdfminer (via pdfplumber) em PDFs da CVM, medidos no banco:
#
# 1. "(cid:N)": o glifo não tem mapeamento para Unicode. Em fontes simples com
#    WinAnsi, N é o próprio byte (231 → ç). Mas na maioria dos documentos com
#    "(cid:" a fonte é Identity-H e N é índice de glifo ("(cid:68)" não é "D"),
#    irrecuperável sem a fonte. Só dá para reparar quando todos os códigos ≥ 32 do
#    documento caem em posições que a StandardEncoding não define — é o único
#    jeito de uma fonte simples WinAnsi produzir "(cid:N)".
# 2. Fonte WinAnsi decodificada como Adobe StandardEncoding: o byte 0xE3 (ã) vira
#    o glifo "ordfeminine" (ª), 0xEA (ê) vira "OE" (Œ), 0xF5 (õ) vira "dotlessi" (ı).
#    "Relaçıes", "SuperintendŒncia", "COMISSˆO". Só corrigido quando o documento
#    tem a assinatura, para não tocar ª/Ø legítimos.

# Posições 0x80–0xFF sem glifo na StandardEncoding (pdfminer.latin_enc), exceto as
# que a cp1252 também não define. Um "(cid:N)" fora deste conjunto é índice de glifo.
_CID_LATIN1_OK: frozenset = frozenset(
    list(range(0x80, 0xA1)) + [0xB0, 0xB5, 0xBE, 0xC0, 0xC9, 0xCC]
    + list(range(0xD1, 0xE1)) + [0xE2, 0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF,
                                 0xF0, 0xF2, 0xF3, 0xF4, 0xF6, 0xF7, 0xFC, 0xFD, 0xFE, 0xFF]
) - {0x81, 0x8D, 0x8F, 0x90, 0x9D}
# Dos que classificam o documento, os que viram caractere. 0x80–0x9F só € … ‘ ’ “ ” • – —:
# os outros ((cid:131), (cid:132)) são marcadores de lista em fonte de símbolos, e ƒ/„ no
# lugar seria lixo trocado por lixo.
_CID_SUBSTITUI: frozenset = _CID_LATIN1_OK - (set(range(0x80, 0xA0)) - {0x80, 0x85, *range(0x91, 0x98)})

# Glifo da StandardEncoding → caractere Latin-1 do mesmo byte, só onde o destino é
# letra. Fora: 0xD0 (— → Ð) e 0xEB (º → ë), em que o glifo é comum em texto legítimo.
# “ (0xAA → ª) e ” (0xBA → º) são aspas legítimas também: tratadas por contexto abaixo.
_STD_MOJIBAKE: dict[str, str] = {
    "`": "Á", "´": "Â", "ˆ": "Ã", "˜": "Ä", "¯": "Å", "˘": "Æ", "˙": "Ç", "¨": "È",
    "˚": "Ê", "¸": "Ë", "˝": "Í", "˛": "Î", "ˇ": "Ï",
    "Æ": "á", "ª": "ã", "Ł": "è", "Ø": "é", "Œ": "ê", "æ": "ñ", "ı": "õ",
    "ł": "ø", "ø": "ù", "œ": "ú", "ß": "û",
}
# Assinatura: o glifo no contexto em que só a troca de encoding o produz. Minúscula para
# os de letra minúscula (sintØtico, SuperintendŒncia, necessÆrias, Pœblico), ı antes de
# "e" (Relaçıes, dispıe — o turco "Yatırım" fica de fora), acento solto entre maiúsculas
# (COMISSˆO, MANUTEN˙ˆO) e "ªo"/"ªes" (Sªo, çªo; "V. Sªs." fica de fora). JØRGEN, WIDERØE,
# "Company´s" e "D´Or" existem na base e não contam; ´ e ` nunca contam.
_LETRA = r"A-Za-zÀ-ÖØ-öø-ÿ" + re.escape("".join(_STD_MOJIBAKE))
_MINUSC = r"a-zß-öø-ÿ" + re.escape("ÆŒØıœª")
_MAIUSC = r"A-ZÀ-ÖØ-Þ"
_ACENTO_SOLTO = re.escape("ˆ˜¸˚˝˙")
_RE_CID = re.compile(r"\(cid:(\d+)\)")
_RE_ASSINATURA = re.compile(
    "|".join([
        rf"(?<=[{_MINUSC}])[ŒØÆœ](?=[a-zß-ÿ])",
        rf"(?<=[{_LETRA}])ı(?=e)",
        rf"(?<=[{_MAIUSC}])[{_ACENTO_SOLTO}](?=[{_MAIUSC}{_ACENTO_SOLTO}])",
        rf"(?<=[{_ACENTO_SOLTO}])[{_ACENTO_SOLTO}](?=[{_MAIUSC}])",
        rf"(?<=[{_LETRA}])ª(?=o\b|es\b)",
    ])
)
_RE_MOJIBAKE = re.compile(
    "|".join([
        r"(?<![0-9])ª",                                  # 1ª continua ª; çªo vira ção
        r"(?<=[0-9nN])”",                                # n” / 1” → nº / 1º
        r"(?<=[0-9])“",                                  # 1“ → 1ª
        # ` e ´ só viram Á/Â em caixa alta: MOBILI`RIOS, J` — nunca "D´Or" ou "company´s"
        rf"(?<![a-zß-ÿ])[`´](?=[{_MAIUSC}](?:[^a-zß-ÿ]|$))",
        rf"(?<=[{_MAIUSC}])[`´](?![A-Za-zÀ-ÿ])",
        "[" + re.escape("".join(k for k in _STD_MOJIBAKE if k not in "ª`´")) + "]",
    ])
)
_MIN_ASSINATURA = 2


def _cid_char(n: int) -> str:
    return " " if n == 0xA0 else bytes([n]).decode("cp1252")


def repair_pdf_text(s: str | None) -> str | None:
    """Conserta "(cid:N)" de fonte WinAnsi e texto WinAnsi lido como StandardEncoding.

    Pura e idempotente. Texto sem os defeitos volta idêntico; "(cid:N)" de fontes
    Identity-H (índice de glifo) fica como está.
    """
    if not s:
        return s
    # Códigos < 32 aparecem soltos (cid:9, cid:13) até em documento WinAnsi e não decidem nada.
    codigos = {int(n) for n in _RE_CID.findall(s)} - set(range(32))
    if codigos and codigos <= _CID_LATIN1_OK:
        s = _RE_CID.sub(
            lambda m: _cid_char(n) if (n := int(m.group(1))) in _CID_SUBSTITUI else m.group(0), s
        )
    if len(_RE_ASSINATURA.findall(s)) >= _MIN_ASSINATURA:
        def troca(m: re.Match) -> str:
            c = m.group(0)
            return {"ª": "ã", "”": "º", "“": "ª"}.get(c) or _STD_MOJIBAKE[c]
        s = _RE_MOJIBAKE.sub(troca, s)
    return s
