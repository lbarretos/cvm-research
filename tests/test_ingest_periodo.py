"""
Fase 0 da consistência financeira: chave natural com período.

Cobre:
  - _upsert_sqlite com índice único de expressão (COALESCE(dt_ini_exerc,''))
  - process_df (ITR e DFP) preserva trimestre + acumulado e grava st_conta_fixa
"""
import io
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from utils import _upsert_sqlite
import ingest_itr
import ingest_dfp

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def _db():
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _row(dt_ini, vl, cd="3.01"):
    return {
        "cnpj_companhia": "84.429.695/0001-11", "fonte": "ITR", "tipo_doc": "DRE",
        "data_referencia": "2024-06-30", "versao": 1, "ordem_exercicio": "Último",
        "dt_ini_exerc": dt_ini, "dt_fim_exerc": "2024-06-30",
        "cd_conta": cd, "ds_conta": "Receita", "vl_conta": vl, "st_conta_fixa": "S",
    }


def test_upsert_mantem_trimestre_e_acumulado():
    conn = _db()
    rows = [_row("2024-01-01", 17_307_730_000.0), _row("2024-04-01", 9_274_426_000.0)]
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, "dem_contabeis_uniq")
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, "dem_contabeis_uniq")  # idempotente
    got = conn.execute(
        "SELECT dt_ini_exerc, vl_conta FROM demonstrativos_contabeis ORDER BY dt_ini_exerc"
    ).fetchall()
    assert got == [("2024-01-01", 17_307_730_000.0), ("2024-04-01", 9_274_426_000.0)]


def test_upsert_dt_ini_null_conflita_consigo_mesmo():
    """BPA/BPP têm dt_ini_exerc NULL; duas cargas não podem duplicar a linha."""
    conn = _db()
    r = _row(None, 1.0, cd="1")
    r.update({"tipo_doc": "BPA", "vl_conta": 1.0})
    _upsert_sqlite(conn, "demonstrativos_contabeis", [r], "dem_contabeis_uniq")
    r["vl_conta"] = 2.0
    _upsert_sqlite(conn, "demonstrativos_contabeis", [r], "dem_contabeis_uniq")
    got = conn.execute("SELECT COUNT(*), MAX(vl_conta) FROM demonstrativos_contabeis").fetchone()
    assert got == (1, 2.0)


def _csv_rows_itr_2t24():
    """As 4 linhas reais de 3.01 da WEG no ITR 2T24 (itr_cia_aberta_DRE_con_2024.csv)."""
    base = {"CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-06-30", "VERSAO": "1",
            "ESCALA_MOEDA": "MIL", "CD_CONTA": "3.01",
            "DS_CONTA": "Receita de Venda de Bens e/ou Serviços", "ST_CONTA_FIXA": "S"}
    return pd.DataFrame([
        {**base, "ORDEM_EXERC": "PENÚLTIMO", "DT_INI_EXERC": "2023-01-01", "DT_FIM_EXERC": "2023-06-30", "VL_CONTA": "15867479.0000000000"},
        {**base, "ORDEM_EXERC": "PENÚLTIMO", "DT_INI_EXERC": "2023-04-01", "DT_FIM_EXERC": "2023-06-30", "VL_CONTA": "8171322.0000000000"},
        {**base, "ORDEM_EXERC": "ÚLTIMO",    "DT_INI_EXERC": "2024-01-01", "DT_FIM_EXERC": "2024-06-30", "VL_CONTA": "17307730.0000000000"},
        {**base, "ORDEM_EXERC": "ÚLTIMO",    "DT_INI_EXERC": "2024-04-01", "DT_FIM_EXERC": "2024-06-30", "VL_CONTA": "9274426.0000000000"},
    ])


def test_itr_process_df_preserva_trimestre_e_acumulado():
    rows = ingest_itr.process_df(_csv_rows_itr_2t24(), {"84.429.695/0001-11"}, "DRE")
    assert len(rows) == 4
    ultimo = sorted((r["dt_ini_exerc"], r["vl_conta"]) for r in rows if r["ordem_exercicio"] == "Último")
    assert ultimo == [("2024-01-01", 17_307_730_000.0), ("2024-04-01", 9_274_426_000.0)]
    assert {r["st_conta_fixa"] for r in rows} == {"S"}


def test_itr_upsert_ponta_a_ponta_nao_mistura_periodos():
    conn = _db()
    rows = ingest_itr.process_df(_csv_rows_itr_2t24(), {"84.429.695/0001-11"}, "DRE")
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, ingest_itr.CONFLICT)
    n = conn.execute("SELECT COUNT(*) FROM demonstrativos_contabeis").fetchone()[0]
    assert n == 4
    tri = conn.execute("SELECT receita_liquida FROM vw_dre").fetchone()[0]
    acu = conn.execute("SELECT receita_liquida FROM vw_dre_acumulada").fetchone()[0]
    assert (tri, acu) == (9_274_426_000.0, 17_307_730_000.0)


def test_dfp_process_df_grava_dt_ini_e_st_conta_fixa():
    df = pd.DataFrame([{
        "CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-12-31", "VERSAO": "1",
        "ESCALA_MOEDA": "MIL", "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": "2024-01-01", "DT_FIM_EXERC": "2024-12-31",
        "CD_CONTA": "3.04.01.02", "DS_CONTA": "Outras Despesas de Vendas",
        "VL_CONTA": "-2500000.0", "ST_CONTA_FIXA": "N",
    }])
    rows = ingest_dfp.process_df(df, {"84.429.695/0001-11"}, "DRE")
    assert rows[0]["dt_ini_exerc"] == "2024-01-01"
    assert rows[0]["st_conta_fixa"] == "N"


def test_dfp_bpa_sem_dt_ini_fica_none():
    df = pd.DataFrame([{
        "CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-12-31", "VERSAO": "1",
        "ESCALA_MOEDA": "MIL", "ORDEM_EXERC": "ÚLTIMO",
        "DT_FIM_EXERC": "2024-12-31", "CD_CONTA": "1", "DS_CONTA": "Ativo Total",
        "VL_CONTA": "1.0", "ST_CONTA_FIXA": "S",
    }])
    rows = ingest_dfp.process_df(df, {"84.429.695/0001-11"}, "BPA")
    assert rows[0]["dt_ini_exerc"] is None


def test_dfp_st_conta_fixa_celula_em_branco_nao_quebra():
    """Regressão: célula ST_CONTA_FIXA genuinamente vazia no CSV vira NaN (float) mesmo
    com dtype=str (pandas detecta NA antes de aplicar dtype), e `(x or "").strip()`
    quebra com AttributeError porque NaN é truthy. Precisa ser construído via
    pd.read_csv (não pd.DataFrame([{...}]) direto) para reproduzir o bug real —
    ver utils.download_year, que sempre usa pd.read_csv(..., dtype=str)."""
    csv_text = (
        "CNPJ_CIA;DT_REFER;VERSAO;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;"
        "CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA;ST_CONTA_FIXA\n"
        "84.429.695/0001-11;2024-12-31;1;ÚLTIMO;2024-01-01;2024-12-31;"
        "3.01;Receita;1000;MIL;\n"
    )
    df = pd.read_csv(io.StringIO(csv_text), sep=";", dtype=str)
    rows = ingest_dfp.process_df(df, {"84.429.695/0001-11"}, "DRE")
    assert len(rows) == 1
    assert rows[0]["st_conta_fixa"] is None


def test_itr_st_conta_fixa_celula_em_branco_nao_quebra():
    """Mesma regressão do teste acima, para ingest_itr.process_df."""
    csv_text = (
        "CNPJ_CIA;DT_REFER;VERSAO;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;"
        "CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA;ST_CONTA_FIXA\n"
        "84.429.695/0001-11;2024-06-30;1;ÚLTIMO;2024-01-01;2024-06-30;"
        "3.01;Receita;1000;MIL;\n"
    )
    df = pd.read_csv(io.StringIO(csv_text), sep=";", dtype=str)
    rows = ingest_itr.process_df(df, {"84.429.695/0001-11"}, "DRE")
    assert len(rows) == 1
    assert rows[0]["st_conta_fixa"] is None


def test_reingestao_faz_backfill_de_st_conta_fixa_nulo():
    """Migração futura zera st_conta_fixa nas linhas pré-existentes (coluna nova,
    não dava pra herdar da tabela antiga). O plano é que a reingestao completa
    (ingest_dfp.py --historico) preencha o valor real via ON CONFLICT DO UPDATE —
    isso só funciona porque st_conta_fixa não está em EXCLUDED_FROM_UPDATE.
    Este teste prova o backfill ponta a ponta, não só a ausência na exclusion set.
    """
    from utils import EXCLUDED_FROM_UPDATE
    assert "st_conta_fixa" not in EXCLUDED_FROM_UPDATE

    conn = _db()
    # Linha "sobrevivente" da migração: st_conta_fixa NULL, mesma chave natural
    # que será reingerida a seguir.
    pre_migracao = _row("2024-01-01", 17_307_730_000.0)
    pre_migracao["st_conta_fixa"] = None
    _upsert_sqlite(conn, "demonstrativos_contabeis", [pre_migracao], "dem_contabeis_uniq")
    antes = conn.execute(
        "SELECT st_conta_fixa FROM demonstrativos_contabeis WHERE cd_conta = '3.01'"
    ).fetchone()
    assert antes == (None,)

    # Reingestão: mesma chave natural (cnpj/fonte/tipo_doc/data_referencia/versao/
    # cd_conta/ordem_exercicio/dt_ini_exerc), agora com ST_CONTA_FIXA populado.
    df = pd.DataFrame([{
        "CNPJ_CIA": "84.429.695/0001-11", "DT_REFER": "2024-06-30", "VERSAO": "1",
        "ESCALA_MOEDA": "MIL", "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": "2024-01-01", "DT_FIM_EXERC": "2024-06-30",
        "CD_CONTA": "3.01", "DS_CONTA": "Receita",
        "VL_CONTA": "17307730.0000000000", "ST_CONTA_FIXA": "S",
    }])
    rows = ingest_itr.process_df(df, {"84.429.695/0001-11"}, "DRE")
    _upsert_sqlite(conn, "demonstrativos_contabeis", rows, ingest_itr.CONFLICT)

    depois = conn.execute(
        "SELECT COUNT(*), st_conta_fixa FROM demonstrativos_contabeis WHERE cd_conta = '3.01'"
    ).fetchone()
    assert depois == (1, "S")  # backfill via ON CONFLICT DO UPDATE, não linha duplicada


def test_ingestao_multi_tipo_doc_bpa_bpp_dre_convivem_nas_views():
    """Um filing real traz BPA + BPP + DRE juntos no mesmo documento. Nada nos
    outros testes prova que os três tipos coexistem em demonstrativos_contabeis
    sem se atropelar nas views vw_balanco/vw_dre (ex: JOIN por tipo_doc errado
    misturando cd_conta '1'/'2' do balanço com '3.x' da DRE)."""
    conn = _db()
    cnpj = "84.429.695/0001-11"
    comum = {
        "cnpj_companhia": cnpj, "fonte": "DFP", "data_referencia": "2024-12-31",
        "versao": 1, "ordem_exercicio": "Último", "dt_fim_exerc": "2024-12-31",
        "st_conta_fixa": "S",
    }
    bpa = {**comum, "tipo_doc": "BPA", "dt_ini_exerc": None,
           "cd_conta": "1", "ds_conta": "Ativo Total", "vl_conta": 500_000.0}
    bpp = {**comum, "tipo_doc": "BPP", "dt_ini_exerc": None,
           "cd_conta": "2", "ds_conta": "Passivo Total", "vl_conta": 500_000.0}
    dre_receita = {**comum, "tipo_doc": "DRE", "dt_ini_exerc": "2024-01-01",
                   "cd_conta": "3.01", "ds_conta": "Receita", "vl_conta": 200_000.0}
    dre_lucro = {**comum, "tipo_doc": "DRE", "dt_ini_exerc": "2024-01-01",
                 "cd_conta": "3.11", "ds_conta": "Lucro Líquido", "vl_conta": 30_000.0}

    _upsert_sqlite(conn, "demonstrativos_contabeis", [bpa, bpp, dre_receita, dre_lucro],
                   "dem_contabeis_uniq")

    n = conn.execute("SELECT COUNT(*) FROM demonstrativos_contabeis").fetchone()[0]
    assert n == 4

    balanco = conn.execute(
        "SELECT ativo_total, patrimonio_liquido FROM vw_balanco "
        "WHERE cnpj_companhia = ? AND fonte = 'DFP' AND data_referencia = '2024-12-31'",
        (cnpj,),
    ).fetchone()
    # patrimonio_liquido vem de BPP cd_conta='2.03', não cadastrada aqui -> None
    assert balanco == (500_000.0, None)

    dre = conn.execute(
        "SELECT receita_liquida, lucro_liquido FROM vw_dre "
        "WHERE cnpj_companhia = ? AND fonte = 'DFP' AND data_referencia = '2024-12-31'",
        (cnpj,),
    ).fetchone()
    assert dre == (200_000.0, 30_000.0)
