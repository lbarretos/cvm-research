"""
Etapa 4: build_chunks.py (limpeza, trechos, deduplicação, versões) e as ferramentas
search_docs/read_doc do MCP, sobre um banco pequeno montado a partir da migração real.
"""
import os
import sqlite3
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "scripts", "ingest"))
sys.path.insert(0, os.path.join(RAIZ, "scripts", "mcp"))

import build_chunks as bc  # noqa: E402
import cvm_mcp  # noqa: E402

PAR = "Parágrafo {i} sobre a aquisição de participação societária e o pagamento de dividendos. " * 6
CNPJ = "33.000.167/0001-01"


def texto_longo(tag):
    return "\n\n".join(f"{tag} {PAR.format(i=i)}" for i in range(14))


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "c.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE companies (cnpj TEXT, ticker TEXT, nome_cvm TEXT, setor TEXT);
        INSERT INTO companies VALUES ('33.000.167/0001-01','PETR4','PETROBRAS','Petróleo');
        CREATE TABLE ipe_docs (protocolo_entrega TEXT PRIMARY KEY, cnpj_companhia TEXT, categoria TEXT, tipo TEXT,
            especie TEXT, assunto TEXT, data_referencia TEXT, data_entrega TEXT, link_download TEXT,
            texto_extraido TEXT, chars_extraidos INT);
    """)
    conn.executescript(open(os.path.join(RAIZ, "scripts/migrations/2026-10-06_ipe_chunks.sql")).read())
    docs = [
        ("P1", CNPJ, "Fato Relevante", None, None, "Aquisição", "2026-01-10", "2026-01-10", "http://x/1", texto_longo("ALFA")),
        # reapresentação: mesma chave, entregue depois, com o mesmo texto: P1 passa a ser substituído
        ("P2", CNPJ, "Fato Relevante", None, None, "Aquisição", "2026-01-10", "2026-01-15", "http://x/2", texto_longo("ALFA")),
        # outro documento da mesma empresa que repete parte do texto (CM com o mesmo conteúdo)
        ("P3", CNPJ, "Comunicado ao Mercado", None, None, "Aquisição", "2026-01-16", "2026-01-16", "http://x/3", texto_longo("ALFA")),
        ("P4", CNPJ, "Dados Econômico-Financeiros", "Demonstrações Financeiras Anuais Completas", None, "DF", "2026-02-01",
         "2026-02-01", "http://x/4", "fora da camada quente " * 100),
    ]
    conn.executemany("INSERT INTO ipe_docs VALUES (?,?,?,?,?,?,?,?,?,?,NULL)", docs)
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setattr(cvm_mcp, "DB_PATH", path)
    return path


def construir(monkeypatch=None):
    monkeypatch.setattr(sys, "argv", ["build_chunks.py"])
    bc.main()


def test_limpar_junta_hifenizacao_e_remove_cabecalho():
    t = "Relatório Anual\nTexto da pala-\nvra solta.\nRelatório Anual\nOutra linha.\nRelatório Anual\n"
    r = bc.limpar(t)
    assert "palavra" in r and "Relatório Anual" not in r


def test_dividir_respeita_alvo_e_sobrepoe():
    ts = bc.dividir(texto_longo("X"))
    assert len(ts) > 3 and all(len(t) < 3200 for t in ts)
    assert ts[0][-100:] in ts[1]          # a sobreposição de 200 caracteres


def test_dedup_por_empresa_e_versoes(db, monkeypatch):
    construir(monkeypatch)
    c = sqlite3.connect(db)
    n_chunks = c.execute("SELECT COUNT(*) FROM ipe_chunks").fetchone()[0]
    n_ocorr = c.execute("SELECT COUNT(*) FROM ipe_chunk_docs").fetchone()[0]
    assert n_ocorr == 3 * n_chunks        # os três documentos têm o mesmo texto: um trecho, três ocorrências
    # P4 é camada fria: fica sem trechos
    assert c.execute("SELECT COUNT(*) FROM ipe_chunk_docs WHERE protocolo_entrega='P4'").fetchone()[0] == 0
    assert dict(c.execute("SELECT protocolo_entrega, is_latest FROM ipe_versoes")) == {"P1": 0, "P2": 1, "P3": 1, "P4": 1}
    assert c.execute("SELECT substituido_por FROM ipe_versoes WHERE protocolo_entrega='P1'").fetchone()[0] == "P2"
    # o representante é o documento mais recente em que o trecho aparece
    assert {r[0] for r in c.execute("SELECT rep_protocolo FROM ipe_chunks")} == {"P3"}


def test_incremental_nao_duplica(db, monkeypatch):
    construir(monkeypatch)
    c = sqlite3.connect(db)
    antes = c.execute("SELECT COUNT(*) FROM ipe_chunks").fetchone()[0]
    c.close()
    construir(monkeypatch)
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM ipe_chunks").fetchone()[0] == antes
    assert c.execute("SELECT COUNT(*) FROM ipe_chunks_fts WHERE ipe_chunks_fts MATCH 'aquisicao'").fetchone()[0] == antes


def test_search_docs_sem_repeticao_e_com_filtros(db, monkeypatch):
    construir(monkeypatch)
    r = cvm_mcp.search_docs("aquisição dividendos", ticker="PETR4", k=10)
    assert r["colunas"][0] == "protocolo" and len(r["linhas"]) > 0
    trechos = [l[6] for l in r["linhas"]]
    assert len(set(trechos)) == len(trechos)          # nenhum trecho idêntico no top-k
    assert all(l[0] == "P3" for l in r["linhas"])
    assert cvm_mcp.search_docs("aquisição", categorias=["Assembleia"])["linhas"] == []
    assert cvm_mcp.search_docs("aquisição", desde="2026-02-01")["linhas"] == []
    assert cvm_mcp.search_docs("aquisição", ticker="XXXX9")["linhas"] == []


def test_search_docs_versoes_antigas(db, monkeypatch):
    construir(monkeypatch)
    # trecho que só existia no P1 (texto diferente): depois que o P2 o substitui, some da busca padrão
    c = sqlite3.connect(db)
    c.execute("UPDATE ipe_docs SET texto_extraido = ? WHERE protocolo_entrega='P1'",
              ("\n\n".join(f"UNICO {PAR.format(i=i)} zebracornio" for i in range(14)),))
    c.commit()
    c.close()
    monkeypatch.setattr(sys, "argv", ["build_chunks.py", "--rebuild"])
    bc.main()
    assert cvm_mcp.search_docs("zebracornio")["linhas"] == []
    assert len(cvm_mcp.search_docs("zebracornio", versoes_antigas=True)["linhas"]) > 0


def test_search_docs_sintaxe_fts_e_erro_claro(db, monkeypatch):
    construir(monkeypatch)
    assert cvm_mcp.search_docs('"aquisição de participação" OR zzzz')["linhas"]
    assert cvm_mcp.search_docs("aquisi*")["linhas"]
    with pytest.raises(ValueError, match="Consulta vazia"):
        cvm_mcp.search_docs("   ")


def test_read_doc_continua_de_onde_parou(db, monkeypatch):
    construir(monkeypatch)
    a = cvm_mcp.read_doc("P3", ordem=0, max_chars=3000)
    assert a["total_trechos"] > 3 and 0 < len(a["texto"]) <= 3000 and a["proximo_ordem"] is not None
    b = cvm_mcp.read_doc("P3", ordem=a["proximo_ordem"], max_chars=3000)
    assert b["ordem_inicio"] == a["proximo_ordem"]
    inteiro = cvm_mcp.read_doc("P3", max_chars=28_000)
    assert inteiro["proximo_ordem"] is None or inteiro["ordem_fim"] < inteiro["total_trechos"]
    assert "\n\n\n" not in a["texto"]


def test_read_doc_camada_fria_le_texto_bruto_por_offset(db, monkeypatch):
    construir(monkeypatch)
    r = cvm_mcp.read_doc("P4", offset=10, max_chars=500)
    assert r["texto"].startswith("a quente") or "quente" in r["texto"]
    assert r["proximo_offset"] == 510 and "camada quente" in r["aviso"]
    with pytest.raises(ValueError, match="não existe"):
        cvm_mcp.read_doc("NAOEXISTE")


def test_atualizar_versoes_escala_linearmente(db):
    """Regressão: o UPDATE de is_latest com subconsulta correlacionada sem índice era O(N²) e não terminava
    com 1,3 mi de trechos. Com 30 mil trechos o laço quadrático leva dezenas de segundos."""
    import time
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO ipe_chunks (cnpj_companhia, cnpj_tok, hash, texto, rep_protocolo, rep_ordem, is_latest)"
                  " VALUES ('c','1',?,'t','P2',0,0)", [(str(i),) for i in range(30_000)])
    c.execute("INSERT INTO ipe_chunk_docs SELECT chunk_id, 'P2', chunk_id FROM ipe_chunks")
    c.commit()
    t = time.time()
    mudou = bc.atualizar_versoes(c)
    assert mudou == 30_000 and time.time() - t < 5
    assert c.execute("SELECT COUNT(*) FROM ipe_chunks WHERE is_latest = 0").fetchone()[0] == 0


# ---------- Etapa 9, bloco A: search_docs(camada=…) sobre o FTS por documento ----------

def _com_fts_documentos(db):
    """Acrescenta ao banco de teste um DF em inglês, um prospecto e o ipe_docs_fts (mesmo schema do real)."""
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO ipe_docs VALUES (?,?,?,?,?,?,?,?,?,?,NULL)", [
        ("P5", CNPJ, "Dados Econômico-Financeiros", "Demonstrações Financeiras Adicionais", None, "ITR", "2026-06-30",
         "2026-08-01", "http://x/5", "Notes. " * 200 + "Reconciliation of income tax: Tax incentives 131,413 143,303. "
         + "Other notes. " * 50),
        ("P6", CNPJ, "Documentos de Oferta de Distribuição Pública", "Prospecto", None, "Oferta", "2025-05-01",
         "2025-05-01", "http://x/6", "Prospecto da oferta com garantia fidejussória e incentivos fiscais. " * 20),
    ])
    c.execute("UPDATE ipe_docs SET texto_extraido = ? WHERE protocolo_entrega = 'P4'",
              ("Notas explicativas. " * 300 + "Conciliação do imposto de renda: Incentivos fiscais 368.062. "
               + "Outras notas. " * 100,))
    c.executescript("""
        CREATE VIRTUAL TABLE ipe_docs_fts USING fts5(protocolo_entrega, cnpj_companhia, assunto, texto_extraido,
            content='ipe_docs', content_rowid='rowid');
        INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild');
    """)
    c.commit()
    c.close()


def _col(r, nome):
    i = r["colunas"].index(nome)
    return [l[i] for l in r["linhas"]]


def test_search_docs_mantem_colunas_antigas_na_ordem(db, monkeypatch):
    construir(monkeypatch)
    r = cvm_mcp.search_docs("aquisição", ticker="PETR4")
    assert r["colunas"][:8] == ["protocolo", "ordem", "data_entrega", "categoria", "tipo", "assunto", "trecho", "link"]
    assert set(_col(r, "camada")) == {"quente"} and set(_col(r, "data_referencia")) == {"2026-01-16"}   # o representante é o P3


def test_search_docs_camada_df_acha_nota_e_devolve_offset(db, monkeypatch):
    construir(monkeypatch)
    _com_fts_documentos(db)
    r = cvm_mcp.search_docs("incentivos fiscais", ticker="PETR4", camada="df")
    assert _col(r, "protocolo") == ["P4"] and _col(r, "camada") == ["df"]
    off = _col(r, "offset")[0]
    assert off is not None
    lido = cvm_mcp.read_doc("P4", offset=off, max_chars=1500)
    assert "368.062" in lido["texto"] and lido["data_referencia"] == "2026-02-01"
    # ITR em inglês (DF Adicionais) e filtro por período do documento
    r = cvm_mcp.search_docs('"tax incentives"', camada="df", ref_desde="2026-06-30")
    assert _col(r, "protocolo") == ["P5"]
    assert cvm_mcp.search_docs('"tax incentives"', camada="df", ref_ate="2026-03-31")["linhas"] == []
    assert cvm_mcp.search_docs("incentivos", camada="df", tipos=["Demonstrações Financeiras Intermediárias"])["linhas"] == []


def test_search_docs_camada_fria_exclui_quente_e_df(db, monkeypatch):
    construir(monkeypatch)
    _com_fts_documentos(db)
    assert _col(cvm_mcp.search_docs("incentivos fiscais", camada="fria"), "protocolo") == ["P6"]
    assert cvm_mcp.search_docs("aquisição", camada="fria")["linhas"] == []      # FR e CM são da quente


def test_search_docs_camada_todas_intercala(db, monkeypatch):
    construir(monkeypatch)
    _com_fts_documentos(db)
    c = sqlite3.connect(db)
    c.execute("UPDATE ipe_docs SET texto_extraido = texto_extraido || ' incentivos fiscais' WHERE protocolo_entrega='P3'")
    c.commit()
    c.close()
    monkeypatch.setattr(sys, "argv", ["build_chunks.py", "--rebuild"])
    bc.main()
    r = cvm_mcp.search_docs("incentivos fiscais", camada="todas", k=5)
    assert set(_col(r, "camada")) == {"quente", "df", "fria"}


def test_search_docs_vazio_aponta_camada_df(db, monkeypatch):
    construir(monkeypatch)
    r = cvm_mcp.search_docs("imposto zebracornio")
    assert r["linhas"] == [] and "camada='df'" in r["aviso"]
    assert "camada='fria'" in cvm_mcp.search_docs("zebracornio")["aviso"]
    with pytest.raises(ValueError, match="camada deve ser"):
        cvm_mcp.search_docs("x", camada="morna")


def test_consulta_fts_tira_stopwords_so_do_texto_livre():
    assert cvm_mcp._consulta_fts("conciliação do imposto de renda") == '"conciliação" AND "imposto" AND "renda"'
    assert cvm_mcp._consulta_fts('"imposto de renda"') == '"imposto de renda"'      # frase fica intacta
    assert cvm_mcp._consulta_fts("de da") == '"de" AND "da"'                          # só stopword: mantém


def test_search_docs_e_read_doc_com_pagina(db, monkeypatch):
    construir(monkeypatch)
    _com_fts_documentos(db)
    c = sqlite3.connect(db)
    # P7 tem 3 páginas separadas por \f; o termo alvo está na página 2 (bem após o início da página)
    c.execute(
        "INSERT INTO ipe_docs VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
        ("P7", CNPJ, "Dados Econômico-Financeiros", "Demonstrações Financeiras Anuais Completas",
         None, "DFP", "2025-12-31", "2026-03-15", "http://x/7",
         ("Página 1: Introdução e sumário executivo. " * 30) + "\f" + \
         ("Página 2: Nota explicativa detalhada. " * 30) + "contingências tributárias relevantes. " + ("Detalhes. " * 30) + "\f" + \
         "Página 3: Outras informações.")
    )
    c.execute("INSERT INTO ipe_docs_fts(ipe_docs_fts) VALUES ('rebuild')")
    c.commit()
    c.close()

    # Documento com \f devolve a página na busca e no read_doc
    r = cvm_mcp.search_docs("contingências tributárias", ticker="PETR4", camada="df")
    assert _col(r, "protocolo") == ["P7"]
    assert _col(r, "pagina") == [2]
    off = _col(r, "offset")[0]
    assert off is not None
    lido = cvm_mcp.read_doc("P7", offset=off)
    assert lido["pagina"] == 2
    assert "contingências tributárias" in lido["texto"]

    # Offset no início cai na página 1
    lido_p1 = cvm_mcp.read_doc("P7", offset=0)
    assert lido_p1["pagina"] == 1

    # Documento antigo sem \f devolve None na busca e omite página no read_doc
    r_antigo = cvm_mcp.search_docs("incentivos fiscais", ticker="PETR4", camada="df")
    assert _col(r_antigo, "protocolo") == ["P4"]
    assert _col(r_antigo, "pagina") == [None]
    lido_antigo = cvm_mcp.read_doc("P4", offset=_col(r_antigo, "offset")[0])
    assert "pagina" not in lido_antigo
