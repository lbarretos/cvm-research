import os
import sqlite3
import sys
import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "scripts", "ingest"))

import rf_devedor_resolucao as R  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(open(os.path.join(RAIZ, "schema.sql")).read())
    yield c
    c.close()


def test_sem_acento_e_norm_tokens():
    assert R.sem_acento("São Paulo - Açúcar & Álcool") == "sao paulo - acucar & alcool"
    assert R.sem_acento("") == ""
    assert R.sem_acento(None) == ""

    tokens = R.norm_tokens("JBS S.A. INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA")
    assert "JBS" in tokens
    assert "SA" not in tokens
    assert "LTDA" not in tokens
    assert "COMERCIO" not in tokens
    assert "ALIMENTOS" not in tokens


def test_resolver_devedor_apelido_canonico():
    match_brf = R.resolver_devedor("BRF S.A.")
    assert match_brf is not None
    assert match_brf["cnpj"] == "01.838.723/0001-27"
    assert match_brf["ticker"] == "BRFS3"
    assert match_brf["metodo"] == "apelido_canonico"

    match_fs = R.resolver_devedor("FS INDUSTRIA DE ETANOL S.A.")
    assert match_fs is not None
    assert match_fs["cnpj"] == "46.710.597/0001-69"
    assert match_fs["ticker"] == "FSII"

    match_crmu = R.resolver_devedor("CARAMURU ALIMENTOS S.A.")
    assert match_crmu is not None
    assert match_crmu["cnpj"] == "00.080.671/0001-00"
    assert match_crmu["ticker"] == "CRMU"


def test_resolver_devedor_companies_match():
    companies = [
        {
            "cnpj": "08.343.492/0001-20",
            "ticker": "MRVE3",
            "nome": "MRV ENGENHARIA E PARTICIPACOES S.A.",
            "norm": R.sem_acento("MRV ENGENHARIA E PARTICIPACOES S.A.").upper(),
            "tokens": R.norm_tokens("MRV ENGENHARIA E PARTICIPACOES S.A."),
        }
    ]

    # Substring match
    res_sub = R.resolver_devedor("MRV ENGENHARIA", companies=companies)
    assert res_sub is not None
    assert res_sub["cnpj"] == "08.343.492/0001-20"
    assert res_sub["metodo"] == "nome_substring"

    # Token match
    res_tok = R.resolver_devedor("MRV HABITACAO", companies=companies)
    # MRV is only 1 token, need len >= 2 or exact, check behavior:
    assert res_tok is None or res_tok["cnpj"] == "08.343.492/0001-20"

    # Unknown
    res_unk = R.resolver_devedor("EMPRESA FANTASMA DESCONHECIDA XYZ 999", companies=companies)
    assert res_unk is None

    # Empty
    assert R.resolver_devedor("") is None
    assert R.resolver_devedor(None) is None


def test_executar_resolucao_dry_run_e_commit(conn):
    # Setup company
    conn.execute("""
        INSERT INTO companies (cnpj, ticker, nome_cvm, setor)
        VALUES ('01.838.723/0001-27', 'BRFS3', 'BRF S.A.', 'Alimentos')
    """)

    # Setup rf_ativos
    conn.execute("""
        INSERT INTO rf_ativos (codigo, tipo, devedor_nome, devedor_cnpj, emissor_nome, fonte)
        VALUES 
          ('CRA001', 'CRA', 'BRF S.A.', NULL, 'ECO SECURITIZADORA', 'teste'),
          ('CRI002', 'CRI', 'DESCONHECIDO XYZ', NULL, 'VERT SECURITIZADORA', 'teste'),
          ('DEB003', 'DEB', 'BRF S.A.', NULL, 'BRF S.A.', 'teste'),
          ('CRA004', 'CRA', 'BRF S.A.', '01.838.723/0001-27', 'ECO SECURITIZADORA', 'teste')
    """)

    # Setup rf_partes
    conn.execute("""
        INSERT INTO rf_partes (chave, codigo, papel, cnpj, nome, fonte, confianca)
        VALUES ('CRA001|devedor|BRF|anbima', 'CRA001', 'devedor', NULL, 'BRF S.A.', 'anbima', 0.8)
    """)
    conn.commit()

    # 1. Test dry_run: 2 candidatos (CRA001, CRI002), 1 resolvido (CRA001), 0 persistido
    res, tot = R.executar_resolucao(conn, dry_run=True)
    assert res == 1
    assert tot == 2

    cur = conn.execute("SELECT devedor_cnpj FROM rf_ativos WHERE codigo = 'CRA001'")
    assert cur.fetchone()[0] is None

    # 2. Test actual run
    res, tot = R.executar_resolucao(conn, dry_run=False)
    assert res == 1
    assert tot == 2

    cur = conn.execute("SELECT devedor_cnpj FROM rf_ativos WHERE codigo = 'CRA001'")
    assert cur.fetchone()[0] == "01.838.723/0001-27"

    # Verify rf_partes updated
    cur = conn.execute("SELECT cnpj FROM rf_partes WHERE codigo = 'CRA001' AND papel = 'devedor'")
    assert cur.fetchone()[0] == "01.838.723/0001-27"

    # DEB003 should not be touched because it's DEB (not CRI/CRA)
    cur = conn.execute("SELECT devedor_cnpj FROM rf_ativos WHERE codigo = 'DEB003'")
    assert cur.fetchone()[0] is None
