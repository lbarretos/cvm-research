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
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Adiciona scripts/ingest ao path para importar utils sem instalar o pacote
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _date, _float, _http_get, _int, _sanitize

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
