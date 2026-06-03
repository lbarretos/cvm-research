"""
Smoke tests para normalização de escala e helpers de conversão dos ingestores CVM.

Cobre:
  - Normalização ESCALA_MOEDA (MIL×1000, UNIDADE×1, escala desconhecida)
  - VL_CONTA vazio / NaN → None (bug fix: float('') levanta ValueError sem _float())
  - _date, _int, _float, _sanitize (helpers compartilhados via utils.py)
  - _http_get: retry em ConnectError/Timeout, falha rápida em erro HTTP
"""
import math
import sys
import os
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

# Adiciona scripts/ingest ao path para importar utils sem instalar o pacote
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _date, _float, _http_get, _int, _sanitize, _upsert_pg, upsert, get_supabase

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


# ── _upsert_pg / upsert dispatch ─────────────────────────────────────────────
# Usa MagicMock para simular conexão psycopg2 sem banco real.
# psycopg2.extras.execute_values é patchado para evitar import real do driver.

def _make_pg_conn():
    """Cria um mock de conexão psycopg2 com context-manager cursor."""
    conn = MagicMock()
    cur = MagicMock()
    # conn.cursor() retorna um context manager que devolve cur
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


@patch("psycopg2.extras.execute_values")
def test_upsert_pg_lista_vazia_retorna_sem_usar_cursor(mock_ev):
    """Rows vazio → early return; cursor e execute_values nunca são chamados."""
    conn, cur = _make_pg_conn()
    _upsert_pg(conn, "companies", [], "cnpj", batch=500)
    conn.cursor.assert_not_called()
    mock_ev.assert_not_called()
    conn.commit.assert_not_called()


@patch("psycopg2.extras.execute_values")
def test_upsert_pg_conflict_coluna_unica(mock_ev):
    """Coluna de conflito simples → ON CONFLICT (cnpj) sem NULLS NOT DISTINCT."""
    conn, cur = _make_pg_conn()
    rows = [{"cnpj": "00.000.000/0001-00", "ticker": "TEST3"}]

    _upsert_pg(conn, "companies", rows, "cnpj", batch=500)

    assert mock_ev.call_count == 1
    sql_used = mock_ev.call_args[0][1]
    assert "ON CONFLICT (cnpj)" in sql_used
    assert "NULLS NOT DISTINCT" not in sql_used
    conn.commit.assert_called_once()


@patch("psycopg2.extras.execute_values")
def test_upsert_pg_conflict_multiplas_colunas(mock_ev):
    """Conflito multi-coluna (csv) → ON CONFLICT (col1,col2) sem NULLS NOT DISTINCT."""
    conn, cur = _make_pg_conn()
    rows = [{"cnpj_companhia": "00.000.000/0001-00", "data_referencia": "2024-01-01", "versao": 1}]

    _upsert_pg(conn, "ipe_docs", rows, "cnpj_companhia,data_referencia", batch=500)

    sql_used = mock_ev.call_args[0][1]
    assert "ON CONFLICT (cnpj_companhia,data_referencia)" in sql_used
    assert "NULLS NOT DISTINCT" not in sql_used
    conn.commit.assert_called_once()


@patch("psycopg2.extras.execute_values")
def test_upsert_pg_named_index_vlmo_mov_uniq(mock_ev):
    """Índice nomeado 'vlmo_mov_uniq' é resolvido para lista de colunas + NULLS NOT DISTINCT."""
    conn, cur = _make_pg_conn()
    rows = [{
        "cnpj_companhia": "00.000.000/0001-00",
        "data_referencia": "2024-01-01",
        "versao": 1,
        "empresa": "Test",
        "tipo_cargo": "Diretor",
        "tipo_movimentacao": "Compra",
        "tipo_ativo": "Ação",
        "caracteristica": "ON",
        "data_movimentacao": "2024-01-05",
        "quantidade": 100,
    }]

    _upsert_pg(conn, "vlmo_movimentacoes", rows, "vlmo_mov_uniq", batch=500)

    sql_used = mock_ev.call_args[0][1]
    # Deve expandir para lista de colunas do índice, não o nome literal
    assert "vlmo_mov_uniq" not in sql_used
    assert "ON CONFLICT (cnpj_companhia,data_referencia,versao,empresa," in sql_used
    assert "NULLS NOT DISTINCT" in sql_used
    conn.commit.assert_called_once()


@patch("psycopg2.extras.execute_values")
def test_upsert_pg_batching_multiplos_lotes(mock_ev):
    """Rows > batch → execute_values chamado uma vez por lote."""
    conn, cur = _make_pg_conn()
    rows = [{"cnpj": f"cnpj_{i}", "ticker": f"T{i}"} for i in range(7)]

    _upsert_pg(conn, "companies", rows, "cnpj", batch=3)

    # 7 rows / batch=3 → 3 lotes (3 + 3 + 1)
    assert mock_ev.call_count == 3
    conn.commit.assert_called_once()


@patch("psycopg2.extras.execute_values")
def test_upsert_pg_exclui_id_e_created_at_do_update_set(mock_ev):
    """Colunas 'id' e 'created_at' não devem aparecer no DO UPDATE SET."""
    conn, cur = _make_pg_conn()
    rows = [{"id": 1, "created_at": "2024-01-01", "cnpj": "00.000.000/0001-00", "ticker": "X3"}]

    _upsert_pg(conn, "companies", rows, "cnpj", batch=500)

    sql_used = mock_ev.call_args[0][1]
    update_part = sql_used.split("DO UPDATE SET")[1]
    assert "id=EXCLUDED.id" not in update_part
    assert "created_at=EXCLUDED.created_at" not in update_part
    assert "ticker=EXCLUDED.ticker" in update_part


def test_upsert_despacha_para_pg_quando_sb_tem_cursor():
    """upsert() usa _upsert_pg quando o objeto 'sb' tem atributo cursor (psycopg2)."""
    conn = MagicMock(spec=["cursor", "commit"])  # spec garante hasattr(sb, 'cursor') == True

    with patch("utils._upsert_pg") as mock_pg:
        sb_mock = MagicMock(spec=["table"])  # sem cursor — garante que o ramo Supabase NÃO foi chamado
        upsert(conn, "companies", [{"cnpj": "x"}], conflict="cnpj", batch=500)
        mock_pg.assert_called_once()
        args = mock_pg.call_args[0]
        assert args[0] is conn
        assert args[1] == "companies"
        assert args[3] == "cnpj"
        sb_mock.table.assert_not_called()  # ramo Supabase não deve ter sido acionado


def test_upsert_despacha_para_supabase_quando_sb_sem_cursor():
    """upsert() usa sb.table().upsert() quando 'sb' não tem cursor (supabase-py)."""
    # Usamos spec para forçar ausência do atributo 'cursor'
    sb = MagicMock(spec=["table"])  # sem 'cursor' no spec

    with patch("utils._upsert_pg") as mock_pg:
        upsert(sb, "companies", [{"cnpj": "x"}], conflict="cnpj", batch=500)
        mock_pg.assert_not_called()  # ramo psycopg2 não deve ter sido acionado

    sb.table.assert_called_once_with("companies")
    sb.table.return_value.upsert.assert_called_once()
    call_kwargs = sb.table.return_value.upsert.call_args
    assert call_kwargs[1]["on_conflict"] == "cnpj"


@patch("psycopg2.extras.execute_values")
def test_upsert_sanitiza_nan_antes_de_chamar_upsert_pg(mock_ev):
    """upsert() aplica _sanitize (NaN→None) antes de despachar para _upsert_pg."""
    import math
    conn, cur = _make_pg_conn()
    rows = [{"cnpj": "00.000.000/0001-00", "valor": math.nan}]

    upsert(conn, "companies", rows, "cnpj", batch=500)

    captured_rows = mock_ev.call_args[0][2]  # terceiro arg de execute_values = list of tuples
    # valor deve ser None, não NaN
    for row_tuple in captured_rows:
        assert all(v is None or v == v for v in row_tuple), "NaN sobreviveu ao _sanitize"


@patch("psycopg2.connect")
def test_get_supabase_usa_psycopg2_quando_database_url_definido(mock_connect):
    """get_supabase() retorna conexão psycopg2 quando DATABASE_URL está definido."""
    fake_conn = MagicMock()
    mock_connect.return_value = fake_conn

    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}, clear=False):
        result = get_supabase()

    mock_connect.assert_called_once_with("postgresql://localhost/test")
    assert result is fake_conn


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
