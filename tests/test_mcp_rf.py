"""
MCP cvm-research, ferramentas de renda fixa (Etapa 8): resolve_bond, get_bond, search_bonds, search_bond_docs e
read_bond_doc sobre a base de teste fictícia de tests/fixtures/rf/make_test_db.py.
"""
import json
import os
import sqlite3
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "scripts", "mcp"))
sys.path.insert(0, os.path.join(RAIZ, "scripts", "ingest"))
sys.path.insert(0, os.path.join(RAIZ, "tests", "fixtures", "rf"))

import cvm_mcp  # noqa: E402
import make_test_db as M  # noqa: E402


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    path = tmp_path_factory.mktemp("rf") / "rf_teste.db"
    M.montar(path).close()
    return path


@pytest.fixture(autouse=True)
def usa_base(base, monkeypatch):
    monkeypatch.setattr(cvm_mcp, "DB_PATH", base)


def _linhas(secao):
    return [dict(zip(secao["colunas"], l)) for l in secao["linhas"]]


def test_resolve_bond_por_codigo_nome_e_cnpj():
    assert [l[0] for l in cvm_mcp.resolve_bond("rumob6")["linhas"]] == ["RUMOB6"]
    assert [l[0] for l in cvm_mcp.resolve_bond("alfa logística")["linhas"]] == ["RUMOB6"]
    # CNPJ da ALFA: emissora do RUMOB6 e fiadora (no PDF) do CRA024004SB
    assert {l[0] for l in cvm_mcp.resolve_bond("11111111000111")["linhas"]} == {"RUMOB6", "CRA024004SB"}
    r = cvm_mcp.resolve_bond("XPTO11")
    assert r["linhas"] == [] and "não está" in r["aviso"]


def test_get_bond_debenture_completo():
    r = cvm_mcp.get_bond("RUMOB6")
    emis = _linhas(r["emissao"])[0]
    assert emis["remuneracao"] == "IPCA + 6,0000%" and emis["taxa_indicativa"] is not None
    fiador = [p for p in _linhas(r["partes"]) if p["papel"] == "fiador"]
    assert fiador and fiador[0]["cnpj"] == M.HOLDING and fiador[0]["fonte"] == "pdf" and fiador[0]["evidencia"]
    assert {g["tipo"] for g in _linhas(r["garantias"])} == {"fianca", "quirografaria"}
    grupo = {(g["cnpj_origem"], g["nivel"], g["controlador_doc"]) for g in _linhas(r["grupo"])}
    assert (M.ALFA, 1, M.HOLDING) in grupo and (M.ALFA, 2, "12345678900") in grupo
    # mesmo grupo: ERDVB4 (BETA, controlada pela HOLDING) e o CRA em que a ALFA é fiadora
    assert {a["codigo"] for a in _linhas(r["ativos_do_grupo"])} == {"ERDVB4", "CRA024004SB"}
    assert len(r["taxas"]["linhas"]) == 22
    assert [d["doc_id"] for d in _linhas(r["documentos"])] == ["TESTE-ESC-RUMOB6"]
    assert "aviso" not in r
    assert len(json.dumps(r, ensure_ascii=False, default=str)) <= cvm_mcp.MAX_RESPONSE_CHARS + 2000


def test_get_bond_cra_lastro_e_securitizadora_fora_do_grupo():
    r = cvm_mcp.get_bond("cra024004sb")
    lastro = _linhas(r["lastro"])
    assert [l["tipo_lastro"] for l in lastro] == ["CPR-F"] and lastro[0]["devedor_cnpj"] == M.DELTA
    assert _linhas(r["ofertas"])[0]["numero_registro"] == "TESTE/2024/001"
    origens = {g["cnpj_origem"] for g in _linhas(r["grupo"])}
    assert M.SECURIT not in origens and M.ALFA in origens
    # a securitizadora não liga o CRA02300796 (mesma securitizadora, outro devedor) ao grupo
    assert "CRA02300796" not in {a["codigo"] for a in _linhas(r["ativos_do_grupo"])}


def test_get_bond_sem_pdf_avisa():
    r = cvm_mcp.get_bond("CRA02300796")
    assert r["garantias"]["linhas"] == [] and r["lastro"]["linhas"] == []
    assert "ingest_rf_docs.py --codigo CRA02300796" in r["aviso"]
    assert "sem taxa ANBIMA" in r["aviso"]


def test_get_bond_codigo_desconhecido():
    assert "não encontrado" in cvm_mcp.get_bond("NADA99")["aviso"]


def test_search_bonds_filtros_e_grupo():
    todos = cvm_mcp.search_bonds()
    assert len(todos["linhas"]) == 4
    assert [l[0] for l in cvm_mcp.search_bonds(tipo="CRA", indexador="IPCA")["linhas"]] == ["CRA024004SB"]
    assert [l[0] for l in cvm_mcp.search_bonds(vence_ate="2029-01-01")["linhas"]] == ["CRA02300796"]
    grupo = {l[0] for l in cvm_mcp.search_bonds(grupo_de=M.BETA)["linhas"]}
    assert grupo == {"RUMOB6", "ERDVB4", "CRA024004SB"}
    assert {l[0] for l in cvm_mcp.search_bonds(so_com_taxa=True)["linhas"]} == {"RUMOB6", "ERDVB4", "CRA024004SB"}


def test_busca_e_leitura_dos_documentos():
    r = cvm_mcp.search_bond_docs("fundo de reserva")
    assert [l[0] for l in r["linhas"]] == ["TESTE-TERMO-CRA"] and "[reserva]" in r["linhas"][0][4]
    assert cvm_mcp.search_bond_docs("fiança", codigo="CRA024004SB")["linhas"] == []
    d = cvm_mcp.read_bond_doc("TESTE-TERMO-CRA", max_chars=500)
    assert d["texto"].lstrip().startswith("TERMO DE SECURITIZAÇÃO") and d["proximo_offset"] == 500
    with pytest.raises(ValueError):
        cvm_mcp.read_bond_doc("NAO-EXISTE")


def test_banco_sem_tabelas_de_renda_fixa(tmp_path, monkeypatch):
    path = tmp_path / "velho.db"
    sqlite3.connect(path).execute("CREATE TABLE companies (cnpj TEXT)").connection.close()
    monkeypatch.setattr(cvm_mcp, "DB_PATH", path)
    with pytest.raises(ValueError, match="2026-10-30_renda_fixa.sql"):
        cvm_mcp.get_bond("RUMOB6")
