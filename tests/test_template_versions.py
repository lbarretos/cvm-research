"""
Etapa 5: versão do template de contas da CVM por filing, crosswalk entre versões e o efeito nas
Camadas 2, 3 e 5. O cenário é o da empresa 00.864.214/0001-06 do stress test: layout antigo, novo
(IFRS 9 desloca 1.02.01.03 em diante), antigo de novo e novo outra vez.
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

import check_cross_period as c2  # noqa: E402
import check_text_stability as c5  # noqa: E402
from consistency_utils import carregar_de_para, latest_rows  # noqa: E402
from filings import rebuild_filings  # noqa: E402
from test_views_plano_contas import _db  # noqa: E402

CNPJ = "00.864.214/0001-06"
ANTIGO = {"1.02.01.03": "Contas a Receber", "1.02.01.04": "Estoques", "1.02.01.05": "Ativos Biológicos"}
NOVO = {"1.02.01.03": "Aplicações ao Custo Amortizado", "1.02.01.04": "Contas a Receber",
        "1.02.01.05": "Estoques", "1.02.01.06": "Ativos Biológicos"}
COLS = ["cnpj_companhia", "fonte", "tipo_doc", "data_referencia", "versao", "ordem_exercicio", "dt_ini_exerc",
        "dt_fim_exerc", "cd_conta", "ds_conta", "vl_conta", "st_conta_fixa"]
# versão do template por trimestre: antigo, novo, antigo, novo
SEQ = [("2018-03-31", ANTIGO), ("2018-06-30", NOVO), ("2019-03-31", ANTIGO), ("2019-06-30", NOVO)]


def _bpa(conn, data, contas, valores=None, cnpj=CNPJ):
    rows = [(cnpj, "ITR", "BPA", data, 1, "Último", None, data, cd, ds, (valores or {}).get(ds, 100.0), "S")
            for cd, ds in contas.items()]
    rows.append((cnpj, "ITR", "BPA", data, 1, "Último", None, data, "1", "Ativo Total", 1000.0, "S"))
    # a DRE com 3.01 padrão fixa o plano_contas do filing em 'padrao'
    rows.append((cnpj, "ITR", "DRE", data, 1, "Último", data[:4] + "-01-01", data, "3.01",
                 "Receita de Venda de Bens e/ou Serviços", 1.0, "S"))
    conn.executemany(f"INSERT INTO demonstrativos_contabeis ({','.join(COLS)}) VALUES ({','.join('?' * 12)})", rows)


def _cenario():
    conn = _db()
    for data, contas in SEQ:
        _bpa(conn, data, contas)
    # uma segunda empresa só com o layout novo, para o plano_cvm ter as duas versões com apoio
    _bpa(conn, "2018-06-30", NOVO, cnpj="11.111.111/0001-11")
    rebuild_filings(conn)
    return conn


def test_versao_por_filing_volta_ao_layout_antigo():
    conn = _cenario()
    v = dict(conn.execute("SELECT data_referencia, versao_template FROM filings WHERE cnpj_companhia = ? "
                          "AND tipo_doc = 'BPA' ORDER BY 1", (CNPJ,)))
    assert [v[d] for d, _ in SEQ] == ["v1", "v2", "v1", "v2"]


def test_plano_cvm_e_crosswalk_derivado_pelo_nome():
    conn = _cenario()
    dp = {(r[0], r[1]): r[2:] for r in conn.execute(
        "SELECT versao_a, cd_a, versao_b, cd_b, ds_conta_norm FROM plano_cvm_de_para WHERE tipo_doc = 'BPA'")}
    # Estoques: 1.02.01.04 na v1 → 1.02.01.05 na v2; Ativos Biológicos: .05 → .06
    assert dp[("v1", "1.02.01.04")][:2] == ("v2", "1.02.01.05")
    assert dp[("v1", "1.02.01.05")][:2] == ("v2", "1.02.01.06")
    assert carregar_de_para(conn)[("padrao", "BPA", "v2", "v1")]["1.02.01.05"] == "1.02.01.04"


def test_camada2_nao_acusa_reclassificacao_na_troca_de_versao():
    conn = _cenario()
    df = latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA")
    # baseline = ITR 1T18 (v1); o 2T18 (v2) traz os mesmos valores nos códigos deslocados, e o
    # 'Estoques' da v2 vale 100 (igual ao da v1). Sem a tradução, 1.02.01.04 compara Estoques com
    # Contas a Receber de outro valor.
    # (a tolerância absoluta da Camada 2 é R$ 1.000: os valores têm de ser de milhões)
    df["vl_conta"] = 100e6
    df.loc[df["ds_conta"] == "Estoques", "vl_conta"] = 777e6
    # o 'Penúltimo' do 2T18 repete o 31/03/2018 para o período comparável
    pen = df[df["data_referencia"] == "2018-06-30"].copy()
    pen["ordem_exercicio"] = "Penúltimo"
    pen["periodo_fim"] = "2018-03-31"
    df = pd.concat([df[df["data_referencia"] == "2018-03-31"], pen], ignore_index=True)
    de_para = carregar_de_para(conn)
    sem, _ = c2.check_cross_period(df)
    com, _ = c2.check_cross_period(df, de_para=de_para)
    linhas_sem = {f["cd_conta"] for f in sem if f["cd_conta"]}
    linhas_com = {f["cd_conta"] for f in com if f["cd_conta"]}
    assert "1.02.01.04" in linhas_sem          # o falso positivo que a etapa quer eliminar
    assert "1.02.01.04" not in linhas_com and "1.02.01.05" not in linhas_com


def test_camada5_nao_confia_no_codigo_fixo_entre_versoes():
    conn = _cenario()
    df = latest_rows(conn, cnpj=CNPJ, tipo_doc="BPA")
    rows, _, _ = c5.check_text_stability(df)
    por = {(r["data_referencia"], r["cd_conta"]): r for r in rows}
    # 1T18 (v1) → 2T18 (v2): 1.02.01.05 passou de Ativos Biológicos para Estoques; o código S não vale
    r = por[("2018-06-30", "1.02.01.05")]
    assert r["classificacao"] == "renumerado" and r["cd_conta_anterior"] == "1.02.01.04"
    # sem versão (coluna ausente) o comportamento antigo se mantém: nada gravado para a troca
    rows_ant, _, _ = c5.check_text_stability(df.drop(columns=["versao_template", "plano_contas"]))
    assert ("2018-06-30", "1.02.01.05") not in {(r["data_referencia"], r["cd_conta"]) for r in rows_ant
                                                if r["classificacao"] == "renumerado"}
