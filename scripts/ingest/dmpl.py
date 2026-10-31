"""
DMPL (demonstração das mutações do patrimônio líquido) do DFP e do ITR → tabela `dmpl`.

A DMPL é uma matriz: cada conta (5.01 saldos iniciais … 5.04 transações com sócios … 5.07 saldos finais) tem um valor
por componente do PL, a coluna COLUNA_DF do CSV da CVM. Não cabe em demonstrativos_contabeis sem uma coluna a mais, então
tem tabela própria. As 8 colunas do plano padrão viram códigos curtos (`COLUNAS`); coluna fora delas (bancos e
seguradoras usam outras) é gravada pelo nome normalizado, para não perder dado.

Contas fixas que interessam à Etapa 7 (coluna 'pl_consolidado'): 5.04.01 aumentos de capital, 5.04.04 ações em
tesouraria adquiridas, 5.04.06 dividendos, 5.04.07 juros sobre capital próprio. No ITR a DMPL é acumulada no ano.

Chamado por ingest_dfp.py e ingest_itr.py com o CSV que eles já baixam (dfp/itr_cia_aberta_DMPL_con_<ano>.csv).
"""
import re
import unicodedata

import pandas as pd

from utils import SCALE, _date, _int, vl_escalado

DDL = """
CREATE TABLE IF NOT EXISTS dmpl (
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,            -- 'DFP' | 'ITR'
    data_referencia TEXT NOT NULL,
    versao          INTEGER NOT NULL,
    ordem_exercicio TEXT NOT NULL,            -- 'Último' | 'Penúltimo'
    dt_ini_exerc    TEXT NOT NULL,
    dt_fim_exerc    TEXT,
    cd_conta        TEXT NOT NULL,
    coluna          TEXT NOT NULL,            -- componente do PL (ver dmpl.COLUNAS)
    ds_conta        TEXT,
    vl_conta        REAL,                     -- R$ (MIL×1000)
    st_conta_fixa   TEXT,
    PRIMARY KEY (cnpj_companhia, fonte, data_referencia, versao, ordem_exercicio, dt_ini_exerc, cd_conta, coluna)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_dmpl_conta ON dmpl (cnpj_companhia, cd_conta, coluna);
"""

# COLUNA_DF do plano padrão → código curto
COLUNAS = {
    "capital social integralizado": "capital",
    "reservas de capital opcoes outorgadas e acoes em tesouraria": "reservas_capital",
    "reservas de lucro": "reservas_lucro",
    "lucros ou prejuizos acumulados": "lucros_acumulados",
    "outros resultados abrangentes": "ora",
    "patrimonio liquido": "pl",
    "participacao dos nao controladores": "nao_controladores",
    "patrimonio liquido consolidado": "pl_consolidado",
}
ORDEM_MAP = {"ÚLTIMO": "Último", "PENÚLTIMO": "Penúltimo"}


def garantir_schema(conn) -> None:
    conn.executescript(DDL)


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def coluna(nome) -> str | None:
    n = _norm(nome) if nome == nome else ""   # NaN do pandas
    if not n:
        return None
    return COLUNAS.get(n, n.replace(" ", "_"))


def process(df: pd.DataFrame, cnpjs: set, fonte: str) -> list[dict]:
    """CSV da DMPL (dtype=str) → linhas de `dmpl`, só das empresas da watchlist. Linha sem coluna ou sem início de
    período (não acontece no CSV da CVM conferido em 2026-10-30) é descartada."""
    df = df[df["CNPJ_CIA"].isin(cnpjs)]
    rows = []
    for r in df.to_dict("records"):
        escala = r.get("ESCALA_MOEDA", "")
        if escala not in SCALE:
            raise ValueError(f"Escala desconhecida: {escala!r} — CNPJ {r.get('CNPJ_CIA')} DMPL")
        col, ini = coluna(r.get("COLUNA_DF")), _date(r.get("DT_INI_EXERC"))
        if col is None or ini is None:
            continue
        ordem = (r.get("ORDEM_EXERC") or "").strip().upper()
        st = str(r.get("ST_CONTA_FIXA") or "").strip().upper()
        rows.append({
            "cnpj_companhia":  r["CNPJ_CIA"],
            "fonte":           fonte,
            "data_referencia": _date(r.get("DT_REFER")),
            "versao":          _int(r.get("VERSAO")) or 1,
            "ordem_exercicio": ORDEM_MAP.get(ordem, ordem),
            "dt_ini_exerc":    ini,
            "dt_fim_exerc":    _date(r.get("DT_FIM_EXERC")),
            "cd_conta":        r.get("CD_CONTA"),
            "coluna":          col,
            "ds_conta":        r.get("DS_CONTA"),
            "vl_conta":        vl_escalado(r.get("VL_CONTA"), escala, r.get("CD_CONTA")),
            "st_conta_fixa":   st if st in ("S", "N") else None,
        })
    return rows


def gravar(conn, rows: list[dict]) -> int:
    garantir_schema(conn)
    if not rows:
        return 0
    cols = list(rows[0])
    conn.executemany(f"INSERT OR REPLACE INTO dmpl ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [tuple(r[c] for c in cols) for r in rows])
    conn.commit()
    return len(rows)


def main():
    """Carga só da DMPL, sem regravar os demonstrativos: `python dmpl.py --desde 2010` (DFP desde o ano pedido, ITR
    desde max(ano, 2011)). Na manutenção, ingest_dfp/ingest_itr já gravam a DMPL junto."""
    import argparse
    from datetime import date

    from utils import download_year, get_db, watchlist_cnpjs
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--desde", type=int, default=date.today().year - 1)
    a = ap.parse_args()
    conn, cnpjs = get_db(), watchlist_cnpjs()
    garantir_schema(conn)
    for fonte, piso in (("DFP", 2010), ("ITR", 2011)):
        for ano in range(max(a.desde, piso), date.today().year + 1):
            try:
                dfs = download_year(ano, fonte, ["DMPL"])
            except Exception as e:
                print(f"  {fonte} {ano}: ERRO download {e}")
                continue
            if "DMPL" not in dfs:
                print(f"  {fonte} {ano}: sem DMPL no ZIP")
                continue
            print(f"  {fonte} {ano}: {gravar(conn, process(dfs['DMPL'], cnpjs, fonte))} linhas")


if __name__ == "__main__":
    main()
