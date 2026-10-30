"""
Renda fixa (Etapa 8): leitura das fontes (rf_fontes.py), ingestores de cadastro e taxas com HTTP falso,
extração por regra das partes/garantias/lastro (extrai_rf.py), cadeia de controle (rf_grupo.py) e escolha
dos documentos do IPE (ingest_rf_docs.py). Os layouts das fontes são sintéticos: o que se testa é o
mapeamento por apelido e o comportamento quando falta coluna, não o arquivo real.
"""
import io
import os
import sqlite3
import sys
import zipfile
from datetime import date, timedelta
from unittest.mock import MagicMock

import httpx
import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "scripts", "ingest"))
sys.path.insert(0, os.path.join(RAIZ, "tests", "fixtures", "rf"))

import extrai_rf  # noqa: E402
import ingest_rf_cadastro  # noqa: E402
import ingest_rf_docs  # noqa: E402
import ingest_rf_taxas  # noqa: E402
import make_test_db  # noqa: E402
import rf_fontes as F  # noqa: E402
import rf_grupo  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(open(os.path.join(RAIZ, "schema.sql")).read())
    yield c
    c.close()


# ── rf_fontes ────────────────────────────────────────────────────────────────

def test_normalizacoes():
    assert F.fmt_cnpj("02387241000160") == "02.387.241/0001-60"
    assert F.fmt_cnpj("123") is None
    assert F.num_br("1.234,56") == 1234.56 and F.num_br("108,5%") == 108.5 and F.num_br("-") is None
    assert F.num_br("6.4") == 6.4 and F.num_br("1.650") == 1650.0
    assert F.data_br("30/10/2026") == "2026-10-30" and F.data_br("2026-10-30") == "2026-10-30"
    assert F.data_br("NaT") is None and F.data_br(None) is None and F.texto("NaT") is None
    # texto livre da Resolução 160: rótulo, qualificação e travessão não entram no nome
    assert F.nome_antes_do_cnpj("JBS S.A., sociedade por ações, inscrita no CNPJ sob o nº 02.916.265/0001-60.",
                                "02.916.265/0001-60") == "JBS S.A."
    assert F.nome_antes_do_cnpj("Devedora : ELLIOT EMPREENDIMENTOS LTDA _ CNPJ 49.107.103/0001-44Fiador: X",
                                "49.107.103/0001-44") == "ELLIOT EMPREENDIMENTOS LTDA"
    assert F.nome_antes_do_cnpj("JOÃO FORTES ENGENHARIA S.A. - EM RECUPERAÇÃO JUDICIAL - CNPJ 33.035.536/0001-00",
                                "33.035.536/0001-00") == "JOÃO FORTES ENGENHARIA S.A."
    assert F.nome_antes_do_cnpj("BRF S.A. (CNPJ 01.838.723/0001-27)", "60.872.504/0001-23") is None
    assert [F.tipo_por_codigo(c) for c in ("RUMOB6", "ERDVB4", "CRA024004SB", "CRI0230001X", "X")] == \
        ["DEB", "DEB", "CRA", "CRI", "OUTRO"]
    assert F.indexador_de("IPCA + 6,0%") == "IPCA" and F.indexador_de("108% do DI") == "DI"


def test_achar_colunas_por_apelido_e_falta_obrigatoria():
    m = F.achar_colunas(["Código do Ativo", "Índice/ Correção", "Taxa Indicativa"], F.APELIDOS_ANBIMA,
                        obrigatorias=("codigo", "taxa_indicativa"))
    assert m["codigo"] == "Código do Ativo" and m["indice"] == "Índice/ Correção"
    with pytest.raises(F.ColunaAusente, match="taxa_indicativa"):
        F.achar_colunas(["Código", "PU"], F.APELIDOS_ANBIMA, obrigatorias=("codigo", "taxa_indicativa"))


ANBIMA = """ANBIMA - Associação Brasileira das Entidades dos Mercados Financeiro e de Capitais
Taxas de Debêntures - 29/10/2026

DI SPREAD
Código@Nome@Repac./  Venc.@Índice/ Correção@Taxa de Compra@Taxa de Venda@Taxa Indicativa@Desvio Padrão@Intervalo Indicativo Mínimo@Intervalo Indicativo Máximo@PU@% PU Par@Duration@% Reune@Referência NTN-B
ERDVB4@BETA@01/03/2030@DI + 1,8000%@1,6000@1,5000@1,5500@0,0100@1,2000@1,9000@1.003,000000@100,40@980@--@--

IPCA SPREAD
Código@Nome@Repac./  Venc.@Índice/ Correção@Taxa de Compra@Taxa de Venda@Taxa Indicativa@Desvio Padrão@Intervalo Indicativo Mínimo@Intervalo Indicativo Máximo@PU@% PU Par@Duration@% Reune@Referência NTN-B
RUMOB6@ALFA@15/06/2032@IPCA + 6,0000%@6,5000@6,3000@6,4000@0,0200@6,0000@6,8000@1.012,500000@101,20@1.650@--@15/08/2032
* nota de rodapé sem dados
"""


def test_parse_anbima_varios_blocos():
    linhas = F.parse_anbima(ANBIMA.encode("latin-1"), date(2026, 10, 29), "DEB")
    por = {l["codigo"]: l for l in linhas}
    assert set(por) == {"ERDVB4", "RUMOB6"}
    r = por["RUMOB6"]
    assert (r["taxa_indicativa"], r["pu"], r["pct_pu_par"], r["duration_du"]) == (6.4, 1012.5, 101.2, 1650.0)
    assert r["indice"] == "IPCA + 6,0000%" and r["referencia"] == "15/08/2032" and r["data"] == "2026-10-29"
    assert por["ERDVB4"]["referencia"] is None


# Nomes de coluna do export real do SND (conferidos em 2026-10-30, com os espaços sobrando); sem coluna de volume
SND = ("Características das debêntures\tgerado em 30/10/2026\n"
       "Codigo do Ativo\tEmpresa        \tSerie\tEmissao\tSituacao\tISIN\tData de Emissao\t Data de Vencimento\t"
       "Garantia/Especie\tQuantidade Emitida\tValor Nominal na Emissao\tindice\t"
       "Percentual Multiplicador/Rentabilidade\tJuros Criterio Novo - Taxa\tAgente Fiduciario\tCNPJ\t"
       "Deb. Incent. (Lei 12.431)\n"
       "RUMOB6\tALFA [TESTE]\t1\t6\tRegistrado\tBRTEST000001\t15/06/2022\t15/06/2032\tQuirografaria\t"
       "1.500.000\t1.000,00\tIPCA\t\t6,0000\tAGENTE TESTE\t11111111000111\tS\n"
       "ERDVB4\tBETA [TESTE]\t2\t4\tRegistrado\tBRTEST000002\t01/03/2023\t01/03/2030\tQuirografaria\t"
       "800.000\t1.000,00\tDI\t100\t1,8000\tAGENTE TESTE\t55555555000155\tN\n"
       "\tlinha de total\n")


def test_parse_snd():
    linhas = {l["codigo"]: l for l in F.parse_snd(SND.encode("latin-1"))}
    assert set(linhas) == {"RUMOB6", "ERDVB4"}
    r = linhas["RUMOB6"]
    assert r["emissor_cnpj"] == "11.111.111/0001-11" and r["valor_emissao"] == 1.5e9   # quantidade × VN
    assert r["isin"] == "BRTEST000001" and r["data_vencimento"] == "2032-06-15" and r["emissao"] == "6"
    assert r["indexador"] == "IPCA" and r["remuneracao"] == "IPCA + 6,0000%" and r["incentivada_12431"] == 1
    assert linhas["ERDVB4"]["remuneracao"] == "100% do DI + 1,8000%" and linhas["ERDVB4"]["incentivada_12431"] == 0


def _distrib_df():
    """oferta_distribuicao.csv (ritos 400/476), com as colunas reais conferidas em 2026-10-30 (subconjunto)."""
    import pandas as pd
    return pd.DataFrame([
        {"Numero_Registro_Oferta": "R2", "Tipo_Ativo": "Ações", "CNPJ_Emissor": "1", "Nome_Emissor": "X",
         "Emissao": "", "Serie": "", "Data_Registro_Oferta": "", "Valor_Total": "", "Quantidade_Total": "",
         "Juros": "", "Atualizacao_Monetaria": "", "Oferta_Incentivo_Fiscal": "", "Nome_Lider": ""},
        {"Numero_Registro_Oferta": "R3", "Tipo_Ativo": "Debêntures", "CNPJ_Emissor": "11111111000111",
         "Nome_Emissor": "ALFA", "Emissao": "6", "Serie": "1", "Data_Registro_Oferta": "01/06/2022",
         "Valor_Total": "1500000000,00", "Quantidade_Total": "1500000", "Juros": "6,0000%",
         "Atualizacao_Monetaria": "IPCA", "Oferta_Incentivo_Fiscal": "S", "Nome_Lider": "BANCO TESTE"},
    ])


def _r160_df():
    """oferta_resolucao_160.csv: sem série, sem código, com a descrição de garantias, lastro e devedores."""
    import pandas as pd
    return pd.DataFrame([
        {"Numero_Requerimento": "Q1", "Status_Requerimento": "Oferta Encerrada",
         "Valor_Mobiliario": "Certificados de Recebíveis do Agronegócio", "CNPJ_Emissor": "66666666000166",
         "Nome_Emissor": "SECURITIZADORA", "Emissao": "240", "Data_Registro": "2024-04-01",
         "Valor_Total_Registrado": "600000000", "Qtde_Total_Registrada": "600000", "Publico_alvo": "Profissional",
         "Tipo_lastro": "CPR-F",
         "Descricao_garantias": "Fiança prestada pela controladora e cessão fiduciária de recebíveis.",
         "Descricao_lastro": "Cédula de Produto Rural Financeira emitida pela Devedora.",
         "Identificacao_devedores_coobrigados": "AGRO DELTA S.A., CNPJ 77.777.777/0001-77",
         "Titulo_incentivado": "Sim", "Agente_fiduciario": "AGENTE TESTE", "Avaliador_Risco": "AGÊNCIA TESTE"},
    ])


def test_parse_cvm_ofertas_so_divida_e_devedor_do_texto():
    distrib = F.parse_cvm_ofertas(_distrib_df(), "cvm_distrib")
    assert [l["numero_registro"] for l in distrib] == ["R3"]            # ações ficam fora
    assert distrib[0]["remuneracao"] == "IPCA 6,0000%" and distrib[0]["incentivada_12431"] == 1
    cra = F.parse_cvm_ofertas(_r160_df(), "cvm_160")[0]
    assert cra["codigo"] is None and cra["serie"] is None             # a CVM não publica
    assert cra["devedor_cnpj"] == "77.777.777/0001-77"                # tirado do texto livre (CNPJ único)
    assert cra["tipo_lastro"] == "CPR-F" and "Fiança" in cra["descricao_garantias"]
    assert cra["avaliador_risco"] == "AGÊNCIA TESTE" and cra["incentivada_12431"] == 1


def test_devedor_do_texto_ambiguo_fica_vazio():
    df = _r160_df()
    df.loc[0, "Identificacao_devedores_coobrigados"] = "A, CNPJ 77.777.777/0001-77; B, CNPJ 88.888.888/0001-88"
    assert F.parse_cvm_ofertas(df, "cvm_160")[0]["devedor_cnpj"] is None


# ── ingest_rf_cadastro ───────────────────────────────────────────────────────

def test_cadastro_snd_manual_e_oferta(conn, monkeypatch, tmp_path):
    w = tmp_path / "rf.csv"
    w.write_text("# comentário\ncodigo,tipo,emissor_cnpj,emissao,serie,observacao\n"
                 "RUMOB6,,,,,só código\nCRA024004SB,CRA,66.666.666/0001-66,240,1,da página da ANBIMA\n")
    monkeypatch.setattr(ingest_rf_cadastro, "RF_WATCHLIST", w)
    monkeypatch.setattr(ingest_rf_cadastro, "get_db", lambda: conn)
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_snd", lambda: F.parse_snd(SND.encode("latin-1")))
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_ofertas", lambda: F.parse_cvm_ofertas(_distrib_df(), "cvm_distrib")
                        + F.parse_cvm_ofertas(_r160_df(), "cvm_160"))
    monkeypatch.setattr(sys, "argv", ["x"])
    ingest_rf_cadastro.main()
    ingest_rf_cadastro.main()   # idempotente
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT codigo, tipo, fonte, devedor_cnpj, valor_emissao, agente_fiduciario FROM rf_ativos")}
    assert rows["RUMOB6"][:2] == ("DEB", "snd")                       # SND prevalece; o manual sem CNPJ é ignorado
    assert rows["RUMOB6"][4] == "AGENTE TESTE"                        # o SND tem o seu; a oferta não sobrescreve
    assert rows["CRA024004SB"] == ("CRA", "manual", "77.777.777/0001-77", 6e8, "AGENTE TESTE")
    assert conn.execute("SELECT COUNT(*) FROM rf_ofertas").fetchone()[0] == 2
    garantias = {r[0] for r in conn.execute(
        "SELECT tipo FROM rf_garantias WHERE codigo = 'CRA024004SB' AND fonte = 'cvm_oferta'")}
    assert garantias == {"fianca", "cessao_fiduciaria"}
    assert conn.execute("SELECT tipo_lastro FROM rf_lastro WHERE codigo = 'CRA024004SB'").fetchall() == [("CPR-F",)]
    papeis = {(c, p) for c, p in conn.execute("SELECT codigo, papel FROM rf_partes WHERE fonte = 'cadastro'")}
    assert {("CRA024004SB", "securitizadora"), ("CRA024004SB", "devedor"), ("RUMOB6", "emissor"),
            ("RUMOB6", "agente_fiduciario")} <= papeis


def test_manual_nao_sobrescreve_snd(conn):
    conn.execute("INSERT INTO rf_ativos (codigo, tipo, emissor_cnpj, fonte) VALUES ('RUMOB6', 'DEB', 'x', 'snd')")
    n = ingest_rf_cadastro.cadastrar_manuais(conn, [{"codigo": "RUMOB6", "tipo": "DEB", "emissor_cnpj": "y",
                                                     "emissao": "6", "serie": None}])
    assert n == 0 and conn.execute("SELECT emissor_cnpj FROM rf_ativos").fetchone() == ("x",)


def test_cadastro_falha_total_sai_com_erro(conn, monkeypatch):
    def quebra():
        raise RuntimeError("fora do ar")
    monkeypatch.setattr(ingest_rf_cadastro, "get_db", lambda: conn)
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_snd", quebra)
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_ofertas", quebra)
    monkeypatch.setattr(sys, "argv", ["x"])
    with pytest.raises(SystemExit):
        ingest_rf_cadastro.main()


# ── ingest_rf_taxas ──────────────────────────────────────────────────────────

def test_taxas_janela_feriado_e_retencao(conn, monkeypatch):
    dias = ingest_rf_taxas.dias_uteis(date.today(), 10)
    feriado = dias[-2]
    chamadas = []

    def get(url, timeout=60):
        chamadas.append(url)
        if feriado.strftime("%y%m%d") in url:
            resp = httpx.Response(404, request=httpx.Request("GET", url))
            raise httpx.HTTPStatusError("404", request=resp.request, response=resp)
        return MagicMock(content=ANBIMA.encode("latin-1"))

    conn.execute("INSERT INTO rf_taxas (codigo, data, tipo, taxa_indicativa) VALUES ('VELHA1', ?, 'DEB', 1)",
                 ((date.today() - timedelta(days=90)).isoformat(),))
    monkeypatch.setattr(ingest_rf_taxas, "get_db", lambda: conn)
    monkeypatch.setattr(ingest_rf_taxas, "_http_get", get)
    monkeypatch.setattr(sys, "argv", ["x", "--dias", "10", "--so-deb"])
    ingest_rf_taxas.main()
    assert len(chamadas) == len(dias)
    datas = {r[0] for r in conn.execute("SELECT DISTINCT data FROM rf_taxas")}
    assert datas == {d.isoformat() for d in dias if d != feriado}       # a velha foi apagada
    chamadas.clear()
    ingest_rf_taxas.main()                                               # só re-tenta o feriado
    assert chamadas == [F.url_anbima("DEB", feriado)]


# ── extrai_rf ────────────────────────────────────────────────────────────────

COLUNAS_ANBIMA_DATA = ["Data de referência", "Tipo", "Código", "Emissor", "Devedor", "Tipo de remuneração",
                       "Taxa de correção", "Série", "Emissão", "Data de vencimento", "Taxa de compra", "Taxa de venda",
                       "Taxa indicativa", "PU Indicativo", "Desvio padrão", "Duration (dias úteis)", "% PU par",
                       "% VNE", "% REUNE", "Referência NTN-B"]


def _planilha_cri_cra(tmp_path):
    """Layout do dataset 'CRIs e CRAs - Precificação ANBIMA' (conferido em 2026-10-30), valores sintéticos.
    O site entrega .xlsx com extensão .xls."""
    import pandas as pd
    nan = float("nan")
    linhas = [
        ["28/10/2026", "CRA", "CRA0000001X", "SEC X S.A.", "DEVEDORA Y S.A.", "IPCA", 6.5, 3, 204, "16/05/2039",
         10.0, nan, 9.6, 939.7, 1.07, 1886.6, 81.8, nan, nan, "15/05/2037"],
        ["29/10/2026", "CRA", "CRA0000001X", "SEC X S.A.", "DEVEDORA Y S.A.", "IPCA", 6.5, 3, 204, "16/05/2039",
         10.2, nan, 9.5877, 940.8, 1.03, 1886.1, 81.9, nan, nan, "15/05/2037"],
        ["29/10/2026", "CRI", "21D0000002", "SEC X S.A.", "Z S.A.", "DI MULTIPLICATIVO", 101.5, 1, 9, "15/10/2030",
         nan, nan, nan, nan, nan, nan, nan, nan, nan, nan],   # sem taxa: entra no cadastro, não em rf_taxas
        ["29/10/2026", "CRI", "21D0000003", "SEC X S.A.", "Z S.A.", "DI ADITIVO", 1.2, 2, 9, "15/10/2031",
         nan, nan, 1.1, 1001.0, nan, 700.0, 100.1, nan, nan, nan],
    ]
    caminho = tmp_path / "certificados-recebiveis-precos.xls"
    pd.DataFrame(linhas, columns=COLUNAS_ANBIMA_DATA).to_excel(caminho, index=False, engine="openpyxl")
    return caminho


def test_remuneracao_anbima_no_formato_do_snd():
    assert F.remuneracao_anbima("IPCA", 6.7825) == "IPCA + 6,7825%"
    assert F.remuneracao_anbima("DI MULTIPLICATIVO", 101.5) == "101,5% do DI"
    assert F.remuneracao_anbima("DI ADITIVO", 1.2) == "DI + 1,2%"
    assert F.remuneracao_anbima("PRE FIXADO", 14.1637) == "14,1637%"
    assert F.indexador_de(F.remuneracao_anbima("DI MULTIPLICATIVO", 101.5)) == "DI"


def test_planilha_cri_cra_taxas_e_cadastro_do_dia_mais_recente(tmp_path):
    taxas, cadastro = F.ler_anbima_data_cri_cra(_planilha_cri_cra(tmp_path))
    assert sorted((t["codigo"], t["data"]) for t in taxas) == [
        ("21D0000003", "2026-10-29"), ("CRA0000001X", "2026-10-28"), ("CRA0000001X", "2026-10-29")]
    t = next(t for t in taxas if t["data"] == "2026-10-29" and t["codigo"] == "CRA0000001X")
    assert (t["taxa_indicativa"], t["indice"], t["referencia"], t["tipo"]) == (9.5877, "IPCA + 6,5%", "15/05/2037", "CRA")
    c = {x["codigo"]: x for x in cadastro}
    assert set(c) == {"CRA0000001X", "21D0000002", "21D0000003"}
    assert (c["CRA0000001X"]["serie"], c["CRA0000001X"]["emissao"], c["CRA0000001X"]["data_vencimento"]) == \
        ("3", "204", "2039-05-16")


def test_arquivo_cri_cra_completa_sem_sobrescrever(conn, tmp_path):
    conn.execute("INSERT INTO rf_ofertas (chave, fonte, emissor_cnpj, emissor_nome) "
                 "VALUES ('k', 'cvm_160', '11.111.111/0001-91', 'SEC X S.A.')")
    conn.execute("INSERT INTO rf_ativos (codigo, tipo, emissor_cnpj, emissao, serie, devedor_nome, fonte) "
                 "VALUES ('CRA0000001X', 'CRA', '08.769.451/0001-08', '204', '3', 'JBS S.A.', 'manual')")
    n, novos = ingest_rf_taxas.carregar_arquivo_cri_cra(conn, _planilha_cri_cra(tmp_path))
    assert (n, novos) == (3, 2)
    r = conn.execute("SELECT emissor_cnpj, devedor_nome, remuneracao, data_vencimento, fonte FROM rf_ativos "
                     "WHERE codigo = 'CRA0000001X'").fetchone()
    assert r == ("08.769.451/0001-08", "JBS S.A.", "IPCA + 6,5%", "2039-05-16", "manual")   # manual prevalece
    assert conn.execute("SELECT emissor_cnpj, fonte FROM rf_ativos WHERE codigo = '21D0000002'").fetchone() == \
        ("11.111.111/0001-91", "anbima")   # CNPJ da securitizadora pelo nome nas ofertas
    assert ingest_rf_taxas.carregar_arquivo_cri_cra(conn, _planilha_cri_cra(tmp_path)) == (3, 0)   # idempotente


def test_extrai_partes_papeis_e_nomes():
    r = extrai_rf.extrair(make_test_db.ESCRITURA_RUMOB6, "DEB")
    partes = {(p["papel"], p["cnpj"]): p["nome"] for p in r["partes"]}
    assert partes == {
        ("emissor", make_test_db.ALFA): "ALFA LOGÍSTICA S.A. [TESTE]",
        ("agente_fiduciario", make_test_db.AGENTE): "AGENTE TESTE DTVM LTDA.",
        ("fiador", make_test_db.HOLDING): "HOLDING ALFA PARTICIPAÇÕES S.A. [TESTE]",
    }
    assert all(make_test_db.ALFA in p["evidencia"] or p["papel"] != "emissor" for p in r["partes"])


def test_extrai_garantias_ignora_negacao():
    tipos = {g["tipo"] for g in extrai_rf.extrair(make_test_db.ESCRITURA_RUMOB6, "DEB")["garantias"]}
    assert tipos == {"fianca", "quirografaria"}    # "não contarão com alienação fiduciária" não entra


def test_extrai_cra_securitizadora_devedor_e_lastro():
    r = extrai_rf.extrair(make_test_db.TERMO_CRA, "CRA")
    papeis = {p["papel"]: p["cnpj"] for p in r["partes"]}
    assert papeis["securitizadora"] == make_test_db.SECURIT       # “Emissora” no CRA é a securitizadora
    assert papeis["devedor"] == make_test_db.DELTA and papeis["fiador"] == make_test_db.ALFA
    assert [l["tipo_lastro"] for l in r["lastro"]] == ["CPR-F"]   # o CPR genérico não duplica
    assert {g["tipo"] for g in r["garantias"]} == {"cessao_fiduciaria", "fundo_reserva"}


def test_extrai_cnpj_sem_termo_definido_nao_vira_parte():
    t = "Banco Coordenador S.A., instituição financeira, inscrita no CNPJ 99.999.999/0001-99, atuará como coordenador."
    assert extrai_rf.extrair(t, "DEB")["partes"] == []


def test_gravar_liga_prestador_e_nao_toca_cadastro(conn):
    conn.execute("INSERT INTO rf_ativos (codigo, tipo, fonte) VALUES ('RUMOB6', 'DEB', 'teste')")
    conn.execute("INSERT INTO rf_partes (chave, codigo, papel, nome, fonte, confianca) "
                 "VALUES ('RUMOB6|emissor|x|cadastro', 'RUMOB6', 'emissor', 'X', 'cadastro', 1)")
    r = extrai_rf.extrair(make_test_db.ESCRITURA_RUMOB6, "DEB")
    extrai_rf.gravar(conn, "D1", "RUMOB6", "DEB", r)
    extrai_rf.gravar(conn, "D1", "RUMOB6", "DEB", r)                  # idempotente
    fianca = conn.execute("SELECT prestador_cnpj FROM rf_garantias WHERE tipo = 'fianca'").fetchone()
    assert fianca == (make_test_db.HOLDING,)
    assert conn.execute("SELECT COUNT(*) FROM rf_partes WHERE fonte = 'cadastro'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM rf_partes WHERE fonte = 'pdf'").fetchone()[0] == 3


# ── rf_grupo ─────────────────────────────────────────────────────────────────

def test_grupo_atravessa_cadeia_e_fres(tmp_path):
    conn = make_test_db.montar(tmp_path / "t.db")
    g = conn.execute("SELECT cnpj_origem, nivel, controlador_doc FROM rf_grupo ORDER BY 1, 2").fetchall()
    assert (make_test_db.ALFA, 1, make_test_db.HOLDING) in g
    assert (make_test_db.ALFA, 2, "12345678900") in g                  # holding → família, na cadeia do FRE
    assert (make_test_db.BETA, 2, "12345678900") in g                  # BETA → HOLDING → FRE da HOLDING
    assert not any(c == make_test_db.DELTA for c, _, _ in g)           # sem FRE na base


def test_grupo_para_em_ciclo():
    a, b = "11111111000111", "22222222000122"
    fres = {a: [dict(cnpj_companhia=F.fmt_cnpj(a), data_referencia="2026", id_acionista=1, id_acionista_relacionado=None,
                     acionista="B", tipo_pessoa_acionista="PJ", cpf_cnpj_acionista=b,
                     percentual_total_acoes_circulacao=50, acionista_controlador="S")],
            b: [dict(cnpj_companhia=F.fmt_cnpj(b), data_referencia="2026", id_acionista=2, id_acionista_relacionado=None,
                     acionista="A", tipo_pessoa_acionista="PJ", cpf_cnpj_acionista=a,
                     percentual_total_acoes_circulacao=50, acionista_controlador="S")]}
    c = rf_grupo.cadeia(F.fmt_cnpj(a), fres)
    assert [x["controlador_doc"] for x in c] == [F.fmt_cnpj(b), F.fmt_cnpj(a)]


# ── ingest_rf_docs ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("assunto, tipo_doc, esperado", [
    ("6ª Emissão de Debêntures", "Escritura de Emissão de Debêntures", "certo"),
    ("Aditamento à Escritura da 5ª Emissão", "Escritura de Emissão de Debêntures", "talvez"),
    ("Aviso aos debenturistas", "Comunicado ao Mercado", None),
])
def test_relevancia_debenture(assunto, tipo_doc, esperado):
    ativo = {"codigo": "RUMOB6", "tipo": "DEB", "emissao": "6", "serie": "1"}
    assert ingest_rf_docs.relevante({"tipo": tipo_doc, "assunto": assunto}, ativo) == esperado


def test_relevancia_cra_exige_emissao_e_serie():
    ativo = {"codigo": "CRA024004SB", "tipo": "CRA", "emissao": "240", "serie": "1"}
    doc = {"categoria": "Securitização de Recebíveis", "tipo": "Termo de Securitização"}
    assert ingest_rf_docs.relevante({**doc, "assunto": "1ª Série da 240ª Emissão"}, ativo) == "certo"
    assert ingest_rf_docs.relevante({**doc, "assunto": "2ª Série da 240ª Emissão"}, ativo) == "talvez"
    assert ingest_rf_docs.relevante({**doc, "assunto": "CRA024004SB"}, ativo) == "certo"


@pytest.mark.parametrize("texto, numero, esperado", [
    ("escritura particular da decima sexta emissao de debentures", "016", True),
    ("16a emissao de debentures", "16", True),
    ("14ª (decima quarta) emissao", "14", True),
    ("vigesima primeira emissao", "1", False),        # 'primeira' depois de dezena é outro número
    ("decima oitava emissao", "16", False),
])
def test_cita_numero_por_extenso(texto, numero, esperado):
    assert ingest_rf_docs._cita_numero(texto, numero, "emiss") is esperado


def test_capa_promove_documento_de_assunto_generico():
    # Rumo 16ª: categoria de escrituras, assunto "Emissão de Valores Mobiliários", a emissão só na capa
    ativo = {"codigo": "RUMOB6", "tipo": "DEB", "emissao": "016", "serie": "002"}
    capa = "Página 1 de 90\nESCRITURA PARTICULAR DA DÉCIMA SEXTA EMISSÃO DE DEBÊNTURES SIMPLES, DA RUMO S.A."
    assert ingest_rf_docs._abertura_cita_emissao(capa, ativo)
    assert not ingest_rf_docs._abertura_cita_emissao(capa.replace("SEXTA", "OITAVA"), ativo)


def test_fichas_de_outras_emissoes_e_vedacao_generica_nao_viram_garantia():
    # trechos da escritura da 14ª Ecorodovias (cláusula 8.2) e da 16ª Rumo, ambas quirografárias
    texto = ("ESCRITURA DA 14ª EMISSÃO DE DEBÊNTURES SIMPLES, DA ESPÉCIE QUIROGRAFÁRIA, EM ATÉ 3 SÉRIES, PARA DISTRIBUIÇÃO PÚBLICA. "
             "A Emissora declara que a emissão e a celebração desta Escritura (e) não "
             "implicam na criação de qualquer hipoteca, penhor, usufruto, fideicomisso, encargo ou outro gravame. "
             "8.2. o Agente Fiduciário presta serviços nas seguintes emissões: Emissão 1ª emissão de Debêntures da "
             "Holding do Araguaia S.A. Valor Total da Emissão R$ 1.400.000.000,00 Quantidade 1.400.000 Espécie Real "
             "Garantias Alienação Fiduciária de Ações; Cessão Fiduciária; Garantia Fidejussória Data de Vencimento "
             "15/10/2036 Enquadramento Adimplência Financeira. EMISSORA RAÍZEN S.A. VOLUME TOTAL PREVISTO "
             "1.050.000.000,00 ESPÉCIE Quirografária GARANTIAS Fiança INADIMPLEMENTOS NO PERÍODO N/A")
    tipos = {g["tipo"] for g in extrai_rf.extrair(texto, "DEB")["garantias"]}
    assert tipos == {"quirografaria"}


@pytest.mark.parametrize("origem, rotulo, capa, esperado", [
    ("ipe", "Escrituras e aditamentos de debêntures Escritura da 14ª emissão", "", True),
    ("ipe", "Prospecto de Distribuição Pública Prospecto Preliminar referente à 16ª Emissão", "", False),
    ("ipe", "Relatório de Agente Fiduciário Relatório Anual do Agente Fiduciário - 16a Emissão", "", False),
    ("ipe", "Escrituras e aditamentos de debêntures Emissão de Valores Mobiliários",
     "ESCRITURA PARTICULAR DA DÉCIMA SEXTA EMISSÃO", True),
    ("arquivo", "manual termo.pdf", "", True),
])
def test_so_documento_de_emissao_vai_para_a_extracao(origem, rotulo, capa, esperado):
    assert extrai_rf.documento_de_emissao(origem, rotulo, capa) is esperado


def test_watchlist_aditiva(tmp_path):
    w = tmp_path / "rf.csv"
    ingest_rf_docs.acrescentar_watchlist(["RUMOB6"], w)
    assert w.read_text().splitlines()[0] == "codigo,tipo,emissor_cnpj,emissao,serie,isin,observacao"
    ingest_rf_docs.acrescentar_watchlist(["RUMOB6", "ERDVB4"], w)
    assert ingest_rf_docs.ler_watchlist(w) == ["RUMOB6", "ERDVB4"]


def test_docs_do_ipe_local_ligados_e_texto_reaproveitado(conn, monkeypatch):
    emissor = make_test_db.ALFA
    conn.execute("INSERT INTO rf_ativos (codigo, tipo, emissor_cnpj, emissao, serie, fonte) "
                 "VALUES ('RUMOB6', 'DEB', ?, '6', '1', 'teste')", (emissor,))
    conn.executemany("INSERT INTO ipe_docs (protocolo_entrega, cnpj_companhia, categoria, tipo, assunto, data_entrega, "
                     "link_download, texto_extraido) VALUES (?,?,?,?,?,?,?,?)", [
        ("P1", emissor, "Escritura de Emissão", "Escritura de Emissão de Debêntures", "6ª Emissão", "2022-06-01",
         "https://www.rad.cvm.gov.br/x", make_test_db.ESCRITURA_RUMOB6),
        ("P2", emissor, "Escritura de Emissão", "Escritura de Emissão de Debêntures", "5ª Emissão", "2021-01-01",
         "https://www.rad.cvm.gov.br/y", None),
        ("P3", emissor, "Fato Relevante", None, "Resultado", "2022-01-01", "https://www.rad.cvm.gov.br/z", None),
    ])
    assert ingest_rf_docs.processar_codigo(conn, "RUMOB6") == 1          # só a 6ª emissão
    assert ingest_rf_docs.extrair_textos(conn, ["RUMOB6"], 10) == 0      # texto veio do ipe_docs
    ingest_rf_docs.rebuild_fts(conn)
    extrai_rf.processar(conn, "RUMOB6")
    assert conn.execute("SELECT COUNT(*) FROM rf_partes WHERE fonte = 'pdf'").fetchone()[0] == 3
    assert conn.execute("SELECT doc_id FROM rf_docs_fts WHERE rf_docs_fts MATCH 'fiança'").fetchall() == [("P1",)]


def test_zip_ipe_filtrado_pelo_cnpj(monkeypatch):
    """Emissor fora do watchlist: o ZIP anual do IPE é baixado e filtrado pelo CNPJ (uma vez por ano)."""
    import ingest_ipe
    import pandas as pd
    df = pd.DataFrame([{"CNPJ_Companhia": "A", "Protocolo_Entrega": "1", "Data_Referencia": "2025-01-01",
                        "Data_Entrega": "2025-01-02", "Versao": "1", "Categoria": "Escritura"},
                       {"CNPJ_Companhia": "B", "Protocolo_Entrega": "2", "Data_Referencia": "2025-01-01",
                        "Data_Entrega": "2025-01-02", "Versao": "1", "Categoria": "Escritura"}])
    baixados = []
    monkeypatch.setattr(ingest_ipe, "download_year", lambda ano: baixados.append(ano) or df)
    ingest_rf_docs._ZIPS.clear()
    a = ingest_rf_docs._ipe_do_zip("A", date.today().year)
    ingest_rf_docs._ipe_do_zip("B", date.today().year)
    assert [d["protocolo_entrega"] for d in a] == ["1"] and baixados == [date.today().year]


def test_zip_cvm_lido_por_ler_zip_csvs():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("oferta_resolucao_160.csv", "Tipo_Ativo;CNPJ_Emissor\nDebêntures;11111111000111\n".encode("latin-1"))
        z.writestr("../fora.csv", b"x")
    csvs = F.ler_zip_csvs(buf.getvalue())
    assert list(csvs) == ["oferta_resolucao_160.csv"]


# ── extrai_rf contra trechos de termos reais (tests/fixtures/rf/termos_reais.py) ──────────────────────

import termos_reais  # noqa: E402


@pytest.mark.parametrize("texto, gabarito", [
    (termos_reais.VIRGO_204, termos_reais.GABARITO_VIRGO_204),
    (termos_reais.ECO_243, termos_reais.GABARITO_ECO_243),
], ids=["virgo_204", "eco_243"])
def test_termo_real_bate_com_o_gabarito(texto, gabarito):
    r = extrai_rf.extrair(texto, "CRA")
    assert {(p["papel"], p["cnpj"]): p["nome"] for p in r["partes"]} == gabarito["partes"]
    assert {g["tipo"]: g["escopo"] for g in r["garantias"]} == gabarito["garantias"]
    assert {l["tipo_lastro"] for l in r["lastro"]} == gabarito["lastro"]


def test_termo_real_sem_os_erros_da_regra_antiga():
    """O que a primeira versão tirava desses mesmos documentos: endereço como nome, a securitizadora de outra
    emissão do anexo e garantias da definição de “Ônus”."""
    for texto in (termos_reais.VIRGO_204, termos_reais.ECO_243):
        r = extrai_rf.extrair(texto, "CRA")
        nomes = [p["nome"] or "" for p in r["partes"]]
        assert not any(n.startswith(("CEP", "Pinheiros")) for n in nomes)
        assert "02.332.886/0011-78" not in {p["cnpj"] for p in r["partes"]}       # do anexo de terceiros
        tipos = {g["tipo"] for g in r["garantias"]}
        assert not tipos & {"hipoteca", "penhor", "alienacao_fiduciaria", "cessao_fiduciaria"}   # “Ônus”
        assert not tipos & {"coobrigacao", "garantia_flutuante", "subordinacao"}   # "…: Não há"
        assert not {l["tipo_lastro"] for l in r["lastro"]} & {"CDCA", "CCI"}        # do anexo


def test_ruido_de_pagina_e_cnpj_quebrado():
    t = extrai_rf._limpo("inscrita no CNPJ/MF Página 15 de 341 DocuSign Envelope ID: "
                         "B9ED68B8-3255-42E6-B76D-F8C8F54F77E4 sob o nº 46.710.597/0001- 69.")
    assert t == "inscrita no CNPJ/MF sob o nº 46.710.597/0001-69."


def test_anexo_so_e_cortado_depois_do_indice():
    corpo = "x " * 500
    t = "Índice Anexo VIII - Histórico de Emissões do Agente Fiduciário " + corpo + \
        "Anexo VIII - Histórico de Emissões do Agente Fiduciário outra emissão"
    cortado = extrai_rf._sem_anexo_de_terceiros(t)
    assert cortado.startswith("Índice Anexo VIII") and "outra emissão" not in cortado


def test_gravar_guarda_escopo_e_prestador_do_lastro(conn):
    r = extrai_rf.extrair(termos_reais.ECO_243, "CRA")
    extrai_rf.gravar(conn, "D1", "CRA02300796", "CRA", r)
    rows = dict(conn.execute("SELECT tipo, escopo || '|' || COALESCE(prestador_cnpj, '') FROM rf_garantias"))
    assert rows == {"aval": "lastro|46.710.597/0001-69", "sem_garantia": "titulo|"}
    assert conn.execute("SELECT devedor_cnpj FROM rf_lastro").fetchone() == ("20.003.699/0001-50",)


# ── ingest_rf_docs: documento passado à mão ───────────────────────────────────────────────────────────

def test_url_pre_assinada_grava_sem_token(conn, monkeypatch):
    import extract_pdf
    monkeypatch.setattr(extract_pdf, "fetch_pdf_text", lambda url, dominios=None: "texto do termo")
    url = "https://s3.amazonaws.com/bucket/termo.pdf?X-Amz-Security-Token=SEGREDO&X-Amz-Signature=abc"
    doc = ingest_rf_docs.doc_manual(url=url)
    for c in ("CRA024004SB", "CRA02300796"):
        ingest_rf_docs.ligar_doc(conn, c, doc, "url", None)
    link, doc_id = conn.execute("SELECT link_download, doc_id FROM rf_docs").fetchone()
    assert link == "https://s3.amazonaws.com/bucket/termo.pdf" and "SEGREDO" not in doc_id
    assert conn.execute("SELECT COUNT(*) FROM rf_doc_ativo").fetchone()[0] == 2   # um termo, várias séries
    # o mesmo link com outro token é o mesmo documento
    assert ingest_rf_docs.doc_manual(url=url.replace("SEGREDO", "OUTRO"))["doc_id"] == doc_id


def test_arquivo_local(tmp_path, monkeypatch):
    import extract_pdf
    pdf = tmp_path / "termo.pdf"
    pdf.write_bytes(b"%PDF-1.4 conteudo")
    monkeypatch.setattr(extract_pdf, "pdf_bytes_text", lambda b: "texto" if b.startswith(b"%PDF") else None)
    doc = ingest_rf_docs.doc_manual(arquivo=str(pdf))
    assert doc["doc_id"].startswith("arquivo:") and doc["link_download"] is None and doc["assunto"] == "termo.pdf"
    (tmp_path / "x.pdf").write_bytes(b"nao e pdf")
    assert not ingest_rf_docs.doc_manual(arquivo=str(tmp_path / "x.pdf"))


# ── banco anterior à Etapa 8: os ingestores criam as tabelas ──────────────────────────────────────────

@pytest.fixture
def banco_antigo():
    """Schema atual sem nada de renda fixa, como um banco montado antes da Etapa 8."""
    c = sqlite3.connect(":memory:")
    c.executescript(open(os.path.join(RAIZ, "schema.sql")).read())
    for nome, tipo in c.execute("SELECT name, type FROM sqlite_master WHERE name LIKE 'rf\\_%' ESCAPE '\\' "
                                "OR name LIKE 'vw_rf%' ORDER BY type = 'view' DESC").fetchall():
        if tipo in ("table", "view") and not nome.startswith("rf_docs_fts_"):
            c.execute(f"DROP {'VIEW' if tipo == 'view' else 'TABLE'} IF EXISTS {nome}")
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'rf_ativos'").fetchone()
    yield c
    c.close()


def test_garantir_schema_cria_uma_vez(banco_antigo):
    assert F.garantir_schema_rf(banco_antigo) is True
    assert F.garantir_schema_rf(banco_antigo) is False
    nomes = {r[0] for r in banco_antigo.execute("SELECT name FROM sqlite_master")}
    assert {"rf_ativos", "rf_ofertas", "rf_taxas", "rf_garantias", "rf_docs_fts", "vw_rf_ativo"} <= nomes


def test_cadastro_em_banco_antigo_roda_ate_o_fim(banco_antigo, monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_rf_cadastro, "RF_WATCHLIST", tmp_path / "nao_existe.csv")
    monkeypatch.setattr(ingest_rf_cadastro, "get_db", lambda: banco_antigo)
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_snd", lambda: F.parse_snd(SND.encode("latin-1")))
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_ofertas", lambda: F.parse_cvm_ofertas(_distrib_df(), "cvm_distrib"))
    monkeypatch.setattr(sys, "argv", ["x"])
    ingest_rf_cadastro.main()
    assert banco_antigo.execute("SELECT COUNT(*) FROM rf_ativos").fetchone()[0] == 2


def test_cadastro_falha_total_sai_antes_das_etapas_seguintes(conn, monkeypatch):
    def quebra():
        raise RuntimeError("fora do ar")
    chamou = []
    monkeypatch.setattr(ingest_rf_cadastro, "get_db", lambda: conn)
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_snd", quebra)
    monkeypatch.setattr(ingest_rf_cadastro, "baixar_ofertas", quebra)
    monkeypatch.setattr(ingest_rf_cadastro, "cadastrar_manuais", lambda *a: chamou.append(1))
    monkeypatch.setattr(sys, "argv", ["x"])
    with pytest.raises(SystemExit) as e:
        ingest_rf_cadastro.main()
    assert e.value.code == 1 and not chamou
