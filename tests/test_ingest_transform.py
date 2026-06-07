"""
Smoke tests para normalização de escala e helpers de conversão dos ingestores CVM.

Cobre:
  - Normalização ESCALA_MOEDA (MIL×1000, UNIDADE×1, escala desconhecida)
  - VL_CONTA vazio / NaN → None (bug fix: float('') levanta ValueError sem _float())
  - _date, _int, _float, _sanitize (helpers compartilhados via utils.py)
  - _http_get: retry em ConnectError/Timeout, falha rápida em erro HTTP
  - _upsert_sqlite: upsert via sqlite3 (substituiu _upsert_pg)
"""
import math
import sqlite3
import sys
import os
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

# Adiciona scripts/ingest ao path para importar utils sem instalar o pacote
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _date, _float, _http_get, _int, _sanitize, _upsert_sqlite, upsert, get_supabase

# Constante local que replica a lógica dos ingestores DFP/ITR
SCALE = {"MIL": 1000, "UNIDADE": 1}


def normalize_vl(vl_str: str, escala: str):
    """Replica a normalização de VL_CONTA dos ingestores ingest_dfp / ingest_itr."""
    if escala not in SCALE:
        raise ValueError(f"Escala desconhecida: {escala!r}")
    vl_raw = _float(vl_str)
    return None if vl_raw is None else vl_raw * SCALE[escala]


# ── ESCALA_MOEDA normalization ────────────────────────────────────────────────

def test_normalizacao_mil():
    assert normalize_vl("5000", "MIL") == 5_000_000.0

def test_normalizacao_unidade():
    assert normalize_vl("5000", "UNIDADE") == 5000.0

def test_normalizacao_mil_decimal():
    """Valores decimais (VL_CONTA com centavos) devem escalar corretamente."""
    assert normalize_vl("1234.56", "MIL") == pytest.approx(1_234_560.0)

def test_normalizacao_escala_desconhecida():
    with pytest.raises(ValueError, match="Escala desconhecida"):
        normalize_vl("5000", "MILHAR")

def test_normalizacao_vl_vazio_retorna_none():
    """
    VL_CONTA pode ser string vazia em contas estruturais (ex: '1' Ativo Total).
    pandas com dtype=str carrega células vazias como '' — float('') levantaria
    ValueError sem o uso de _float(). Deve retornar None, não travar o ingestor.
    """
    assert normalize_vl("", "MIL") is None

def test_normalizacao_vl_nan_retorna_none():
    """pandas pode produzir 'nan' como string para células NaN com dtype=str."""
    assert normalize_vl("nan", "MIL") is None


# ── _date helper ─────────────────────────────────────────────────────────────

def test_date_iso():
    assert _date("2024-03-31") == "2024-03-31"

def test_date_formato_br():
    """CVM às vezes usa formato DD/MM/YYYY."""
    result = _date("31/03/2024")
    assert result == "2024-03-31"

def test_date_vazio_retorna_none():
    assert _date("") is None

def test_date_none_retorna_none():
    assert _date(None) is None

def test_date_nan_retorna_none():
    assert _date("nan") is None


# ── _int helper ──────────────────────────────────────────────────────────────

def test_int_string():
    assert _int("42") == 42

def test_int_com_virgula():
    """CVM usa vírgula como separador decimal em alguns campos inteiros."""
    assert _int("1,0") == 1

def test_int_nan_retorna_none():
    assert _int("nan") is None

def test_int_vazio_retorna_none():
    assert _int("") is None


# ── _float helper ────────────────────────────────────────────────────────────

def test_float_string():
    assert _float("1234.56") == pytest.approx(1234.56)

def test_float_virgula_decimal():
    assert _float("1234,56") == pytest.approx(1234.56)

def test_float_nan_retorna_none():
    assert _float("nan") is None

def test_float_vazio_retorna_none():
    assert _float("") is None


# ── _sanitize helper ─────────────────────────────────────────────────────────

def test_sanitize_nan_para_none():
    rows = [{"a": float("nan"), "b": 1, "c": "texto"}]
    result = _sanitize(rows)
    assert result[0]["a"] is None
    assert result[0]["b"] == 1
    assert result[0]["c"] == "texto"

def test_sanitize_preserva_zero():
    """Zero não é NaN — deve ser preservado."""
    rows = [{"x": 0, "y": 0.0}]
    result = _sanitize(rows)
    assert result[0]["x"] == 0
    assert result[0]["y"] == 0.0

def test_sanitize_lista_vazia():
    assert _sanitize([]) == []


# ── _http_get retry ───────────────────────────────────────────────────────────

@patch("utils.time.sleep")
@patch("utils.httpx.get")
def test_http_get_sucesso_direto(mock_get, mock_sleep):
    """Resposta 200 na primeira tentativa — sem retry."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    mock_get.return_value = resp

    result = _http_get("http://exemplo.com", timeout=5)

    assert result is resp
    mock_get.assert_called_once()
    mock_sleep.assert_not_called()


@patch("utils.time.sleep")
@patch("utils.httpx.get")
def test_http_get_retry_sucesso_na_segunda(mock_get, mock_sleep):
    """Falha de rede na primeira tentativa, sucesso na segunda — sem raise."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    mock_get.side_effect = [httpx.ConnectError("timeout"), resp]

    result = _http_get("http://exemplo.com", timeout=5, retries=3)

    assert result is resp
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)  # backoff: 2^0 = 1s


@patch("utils.time.sleep")
@patch("utils.httpx.get")
def test_http_get_esgota_retries(mock_get, mock_sleep):
    """Todas as tentativas falham — ConnectError deve propagar."""
    mock_get.side_effect = httpx.ConnectError("unreachable")

    with pytest.raises(httpx.ConnectError):
        _http_get("http://exemplo.com", timeout=5, retries=3)

    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2  # 2 esperas entre 3 tentativas


@patch("utils.time.sleep")
@patch("utils.httpx.get")
def test_http_get_erro_http_nao_retryta(mock_get, mock_sleep):
    """Erro HTTP (4xx/5xx) não é erro de rede — deve falhar imediatamente."""
    resp = MagicMock()
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    mock_get.return_value = resp

    with pytest.raises(httpx.HTTPStatusError):
        _http_get("http://exemplo.com", timeout=5, retries=3)

    mock_get.assert_called_once()  # sem retry para erros HTTP
    mock_sleep.assert_not_called()


# ── _upsert_sqlite / upsert dispatch ─────────────────────────────────────────
# Usa sqlite3 in-memory para testar _upsert_sqlite sem banco real.

def _make_sqlite_conn():
    """In-memory SQLite connection com schema mínimo para testes."""
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
    assert row[1] == "2020-01-01"  # created_at não deve ser sobrescrito


def test_upsert_sqlite_conflict_multiplas_colunas():
    conn = _make_sqlite_conn()
    rows = [{"cnpj": "x", "fonte": "DFP", "tipo": "DRE"}]
    _upsert_sqlite(conn, "demo", rows, "cnpj,fonte,tipo")
    assert conn.execute("SELECT COUNT(*) FROM demo").fetchone()[0] == 1


def test_upsert_sqlite_named_index_vlmo_mov_uniq():
    """Índice nomeado 'vlmo_mov_uniq' deve ser resolvido para lista de colunas via _INDEX_COLUMNS."""
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
    _upsert_sqlite(conn, "vlmo_movimentacoes", [row], "vlmo_mov_uniq")  # idempotente
    assert conn.execute("SELECT COUNT(*) FROM vlmo_movimentacoes").fetchone()[0] == 1


def test_upsert_despacha_para_sqlite_quando_sb_e_sqlite_connection():
    conn = sqlite3.connect(':memory:')
    with patch("utils._upsert_sqlite") as mock_sq:
        upsert(conn, "companies", [{"cnpj": "x", "ticker": "T"}], conflict="cnpj")
        mock_sq.assert_called_once()
        args = mock_sq.call_args[0]
        assert args[0] is conn
        assert args[1] == "companies"
        assert args[3] == "cnpj"


def test_upsert_despacha_para_supabase_quando_sb_sem_cursor():
    """upsert() usa sb.table().upsert() quando 'sb' não é sqlite3.Connection."""
    sb = MagicMock(spec=["table"])

    with patch("utils._upsert_sqlite") as mock_sq:
        upsert(sb, "companies", [{"cnpj": "x"}], conflict="cnpj", batch=500)
        mock_sq.assert_not_called()

    sb.table.assert_called_once_with("companies")
    sb.table.return_value.upsert.assert_called_once()
    call_kwargs = sb.table.return_value.upsert.call_args
    assert call_kwargs[1]["on_conflict"] == "cnpj"


def test_upsert_sanitiza_nan_antes_de_chamar_upsert_sqlite():
    """upsert() aplica _sanitize (NaN→None) antes de despachar para _upsert_sqlite."""
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE nan_test (cnpj TEXT PRIMARY KEY, valor REAL)")
    rows = [{"cnpj": "00.000.000/0001-00", "valor": math.nan}]
    upsert(conn, "nan_test", rows, "cnpj")
    valor = conn.execute(
        "SELECT valor FROM nan_test WHERE cnpj = '00.000.000/0001-00'"
    ).fetchone()[0]
    assert valor is None


def test_get_supabase_usa_sqlite_quando_database_url_definido():
    """get_supabase() retorna sqlite3.Connection quando DATABASE_URL=sqlite:///... está definido."""
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


def test_get_supabase_usa_supabase_quando_database_url_ausente():
    """get_supabase() usa supabase-py quando DATABASE_URL não está definido."""
    import sys
    import types

    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.limit.return_value.execute.return_value = None
    mock_create = MagicMock(return_value=fake_client)

    # Injeta módulo supabase falso para não depender do pacote real estar instalado
    fake_supabase_mod = types.ModuleType("supabase")
    fake_supabase_mod.create_client = mock_create

    env_sem_db_url = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env_sem_db_url["SUPABASE_URL"] = "https://fake.supabase.co"
    env_sem_db_url["SUPABASE_KEY"] = "fake-key"

    original_mod = sys.modules.get("supabase")
    sys.modules["supabase"] = fake_supabase_mod
    try:
        with patch.dict(os.environ, env_sem_db_url, clear=True):
            result = get_supabase()
    finally:
        if original_mod is None:
            sys.modules.pop("supabase", None)
        else:
            sys.modules["supabase"] = original_mod

    mock_create.assert_called_once_with("https://fake.supabase.co", "fake-key")
    assert result is fake_client


# ── extract_pdf.py fail-fast guard ───────────────────────────────────────────

def test_extract_pdf_failfast_com_sqlite_sem_supabase_url():
    """extract_pdf.main() deve sair com código 1 quando DATABASE_URL=sqlite://... e SUPABASE_URL ausente."""
    import importlib
    import types

    env_sqlite_sem_supabase = {
        k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SUPABASE_URL")
    }
    env_sqlite_sem_supabase["DATABASE_URL"] = "sqlite:///test.db"

    extract_pdf_path = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "ingest", "extract_pdf.py"
    )
    spec = importlib.util.spec_from_file_location("extract_pdf_test", extract_pdf_path)
    extract_pdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract_pdf)

    with patch.dict(os.environ, env_sqlite_sem_supabase, clear=True):
        with pytest.raises(SystemExit) as exc_info:
            extract_pdf.main()
    assert exc_info.value.code == 1


# ── _upsert_sqlite rollback on exception ─────────────────────────────────────

def test_upsert_sqlite_rollback_em_excecao():
    """_upsert_sqlite deve fazer rollback e re-raise quando executemany falha."""
    conn = _make_sqlite_conn()
    bad_rows = [{"cnpj": "x", "ticker": None}]  # ticker TEXT NOT NULL → IntegrityError
    with pytest.raises(Exception):
        _upsert_sqlite(conn, "companies", bad_rows, "cnpj")
    # Conexão deve estar usável após rollback
    count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    assert count == 0
