"""
Testes de utils.repair_pdf_text e do script repair_text_encoding.py.

Os exemplos com defeito são trechos reais de ipe_docs.texto_extraido
(protocolo 014109IPE280820260198868887-26, Randoncorp, ofício CVM de 28/08/2026, e
outros achados na varredura da base). Os que não devem mudar também vêm da base:
apóstrofo com acento agudo, nomes nórdicos/turcos e ordinais legítimos.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import repair_pdf_text
from repair_text_encoding import medir, varrer

RANDON = (
    "(cid:192) COMISSˆO DE VALORES MOBILI`RIOS - CVM\n"
    "SuperintendŒncia de Rela(cid:231)ıes com Empresas - SEP\n"
    "GerŒncia de Acompanhamento de Empresas 3 - GEA-3\n"
    "Ref.: Of(cid:237)cio n” 297/2026/CVM/SEP/GEA-3\n"
    "Assunto: Solicita(cid:231)ªo de manifesta(cid:231)ªo – Negocia(cid:231)ªo em "
    "per(cid:237)odo de veda(cid:231)ªo -\n"
    "Processo: CVM n”19957.013747/2026-02\n"
    "membro do Conselho de Administra(cid:231)ªo da\n"
    "Companhia, acerca das aquisi(cid:231)ıes de a(cid:231)ıes RAPT4 e RAPT4F"
)
RANDON_OK = (
    "À COMISSÃO DE VALORES MOBILIÁRIOS - CVM\n"
    "Superintendência de Relações com Empresas - SEP\n"
    "Gerência de Acompanhamento de Empresas 3 - GEA-3\n"
    "Ref.: Ofício nº 297/2026/CVM/SEP/GEA-3\n"
    "Assunto: Solicitação de manifestação – Negociação em "
    "período de vedação -\n"
    "Processo: CVM nº19957.013747/2026-02\n"
    "membro do Conselho de Administração da\n"
    "Companhia, acerca das aquisições de ações RAPT4 e RAPT4F"
)


def test_documento_randon_inteiro():
    assert repair_pdf_text(RANDON) == RANDON_OK


def test_idempotente():
    assert repair_pdf_text(RANDON_OK) == RANDON_OK
    assert repair_pdf_text(repair_pdf_text(RANDON)) == RANDON_OK


@pytest.mark.parametrize("entrada, esperado", [
    ("(cid:192) COMISSˆO", "À COMISSÃO"),
    ("SuperintendŒncia de Rela(cid:231)ıes", "Superintendência de Relações"),
    ("Solicita(cid:231)ªo de manifesta(cid:231)ªo", "Solicitação de manifestação"),
    ("MOBILI`RIOS e ADMINISTRA˙ˆO e MANUTEN˙ˆO", "MOBILIÁRIOS e ADMINISTRAÇÃO e MANUTENÇÃO"),
    ("Demonstra(cid:231)ıes contÆbeis intermediÆrias", "Demonstrações contábeis intermediárias"),
    ("o sintØtico e o mØtodo Ø o mesmo", "o sintético e o método é o mesmo"),
    ("Sªo Paulo, 1” semestre, 2“ emissªo", "São Paulo, 1º semestre, 2ª emissão"),
    ("pœblico nœmero equivalŒncia", "público número equivalência"),
])
def test_trechos_reais(entrada, esperado):
    # Em documento com a assinatura (aqui garantida pelo prefixo), cada trecho é consertado.
    prefixo = "Rela(cid:231)ıes e Solicita(cid:231)ªo. "
    assert repair_pdf_text(prefixo + entrada) == "Relações e Solicitação. " + esperado


@pytest.mark.parametrize("texto", [
    # Apóstrofo com acento agudo/grave: frequente na base (releases em inglês, nomes).
    "The Company´s Bylaws and the Auditor´s report. Rede D´Or São Luiz. Moody´s",
    "ORKERS`PENSION FUND; Ipiranga do Sul D`Oeste",
    # Ordinais e abreviações legítimas.
    "1ª Emissão de Debêntures, nº 12, V. Sªs., 2º trimestre, Srª Maria",
    # Nomes estrangeiros com Ø, ı, Œ legítimos.
    "Diretor: JØRGEN Kildahl; WIDERØE; Ak Yatırımlar Menkul Değerler; ŒUVRE",
    # Aspas curvas legítimas.
    "o chamado “Contrato” foi aprovado em “Assembleia”",
    "",
])
def test_texto_legitimo_nao_muda(texto):
    assert repair_pdf_text(texto) == texto


def test_none():
    assert repair_pdf_text(None) is None


def test_um_indicio_so_nao_basta():
    # Um "Sªo" isolado pode ser OCR/digitação; com uma só ocorrência o documento fica como está.
    texto = "Endereço: Rua X, Sªo Paulo. Tudo o mais correto: ação, gestão."
    assert repair_pdf_text(texto) == texto


def test_cid_de_fonte_identity_h_fica():
    # Índice de glifo: códigos ASCII e < 32 misturados. chr(N) seria lixo ("(cid:68)" não é "D").
    texto = "(cid:68)(cid:3)(cid:87)(cid:82) Rela(cid:231)ªo"
    assert repair_pdf_text(texto) == texto


def test_cid_menor_que_32_nao_impede_o_reparo():
    texto = "Rela(cid:231)ıes(cid:13) e posi(cid:231)ıes no per(cid:237)odo"
    assert repair_pdf_text(texto) == "Relações(cid:13) e posições no período"


def test_cid_cp1252_e_marcador_de_lista():
    # 0x96 é travessão na cp1252; 0x83 é marcador de lista em fonte de símbolos: fica.
    texto = "Rela(cid:231)ıes (cid:150) Solicita(cid:231)ªo\n(cid:131)\nper(cid:237)odo"
    assert repair_pdf_text(texto) == "Relações – Solicitação\n(cid:131)\nperíodo"


def test_cid_sem_mojibake():
    # Só "(cid:N)" WinAnsi, sem glifo trocado: conserta o cid e não mexe no resto.
    assert repair_pdf_text("patrim(cid:244)nio l(cid:237)quido, 1ª parcela") == \
        "patrimônio líquido, 1ª parcela"


# ── Script de uso único ─────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE ipe_docs (protocolo_entrega TEXT PRIMARY KEY, cnpj_companhia TEXT,
                               assunto TEXT, texto_extraido TEXT, chars_extraidos INTEGER);
        CREATE VIRTUAL TABLE ipe_docs_fts USING fts5(protocolo_entrega, cnpj_companhia, assunto,
                               texto_extraido, content='ipe_docs', content_rowid='rowid');
        CREATE TABLE notas_explicativas (id INTEGER PRIMARY KEY, cnpj_companhia TEXT,
                               texto_extraido TEXT, chars_extraidos INTEGER, updated_at TEXT);
        CREATE VIRTUAL TABLE notas_explicativas_fts USING fts5(cnpj_companhia, texto_extraido,
                               content='notas_explicativas', content_rowid='id');
    """)
    c.executemany("INSERT INTO ipe_docs VALUES (?, 'X', '', ?, ?)", [
        ("p1", RANDON, len(RANDON)),
        ("p2", "Company´s report. Informações corretas.", 40),
        ("p3", None, None),
    ])
    c.execute("INSERT INTO notas_explicativas (id, texto_extraido, chars_extraidos) VALUES (1, ?, 10)",
              ("Informa(cid:231)ıes contÆbeis e Solicita(cid:231)ªo",))
    for fts in ("ipe_docs_fts", "notas_explicativas_fts"):
        c.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")
    c.commit()
    return c


def test_dry_run_nao_grava(conn):
    r = varrer(conn, "ipe_docs", lote=1, aplicar=False)
    assert (r["lidas"], r["mudariam"], r["cid_antes"], r["cid_depois"]) == (2, 1, 1, 0)
    assert conn.execute("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega='p1'").fetchone()[0] == RANDON


def test_aplicar_grava_texto_chars_e_fts(conn):
    antes = medir(conn)
    assert antes[("ipe_docs", "cid")] == 1
    assert antes[("ipe_docs", "solicitacao")] == 0

    varrer(conn, "ipe_docs", lote=1, aplicar=True)
    varrer(conn, "notas_explicativas", lote=1, aplicar=True)
    for fts in ("ipe_docs_fts", "notas_explicativas_fts"):
        conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")

    texto, chars = conn.execute(
        "SELECT texto_extraido, chars_extraidos FROM ipe_docs WHERE protocolo_entrega='p1'").fetchone()
    assert texto == RANDON_OK and chars == len(RANDON_OK)
    assert conn.execute("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega='p2'").fetchone()[0] \
        == "Company´s report. Informações corretas."
    assert conn.execute("SELECT updated_at IS NOT NULL FROM notas_explicativas").fetchone()[0] == 1

    depois = medir(conn)
    assert depois[("ipe_docs", "cid")] == 0
    assert depois[("ipe_docs", "solicitacao")] == 1
    assert depois[("ipe_docs", "informacoes")] == 1      # p2 já batia antes
    assert depois[("notas_explicativas", "informacoes")] == 1
    assert antes[("notas_explicativas", "informacoes")] == 0
