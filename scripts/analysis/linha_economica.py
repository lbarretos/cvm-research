"""
Etapa 6: linha econômica por empresa (camada L1).

As contas que a empresa cria (`st_conta_fixa = 'N'`) trocam de código entre filings: na DFC, o mesmo
código vira outra linha em 52,5% dos pares ITR 3T → DFP. Uma consulta por `cd_conta` mistura contas.
Aqui cada (empresa, tipo_doc) tem uma sequência de filings (ITR e DFP, em ordem de data) e cada conta
de cada filing recebe um `linha_id` que a segue ao longo da série, pela escada de casamento da
Camada 5 (`check_text_stability.match_filings`: estável → renumerado → reformulação → ambíguo).

Tabelas (schema.sql, migração 2026-10-15_linha_economica.sql):
  linha_empresa  uma linha por (empresa, tipo_doc, fonte, data, cd_conta) com o linha_id e como foi ligada
  linha_decisao  decisões humanas sobre pares ambíguos, lidas pelo encadeamento

Par `ambiguo` NÃO encadeia (abre linha nova, com o candidato em cd_conta_anterior): é a fila de revisão.
Uma decisão 'mesma' liga; 'diferente' impede o casamento automático.

    python linha_economica.py --full                       # base inteira (~2 min)
    python linha_economica.py --cnpj 84.429.695/0001-11    # uma empresa
    python linha_economica.py --listar-ambiguos --cnpj 84.429.695/0001-11 [--tipo-doc DFC_MI]
    python linha_economica.py --decidir --cnpj ... --tipo-doc DFC_MI --de-cd 6.03.08 --de-data 2024-09-30 \\
        --para-cd 6.03.09 --para-data 2024-12-31 --decisao mesma --autor lucas
"""
import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime, timezone

from check_text_stability import _linhas, match_filings
from consistency_utils import get_db, latest_rows, normalize_text, parent_code

DDL = """
CREATE TABLE IF NOT EXISTS linha_empresa (
    cnpj_companhia    TEXT NOT NULL,
    tipo_doc          TEXT NOT NULL,
    fonte             TEXT NOT NULL,
    data_referencia   TEXT NOT NULL,
    cd_conta          TEXT NOT NULL,
    linha_id          TEXT NOT NULL,
    ds_conta          TEXT,
    st_conta_fixa     TEXT,              -- 'S' padrão CVM, 'N' criada pela empresa
    casamento         TEXT NOT NULL,     -- primeira | estavel | renumerado | reformulacao | decisao | reatado | reatado_pai | ambiguo | nova
    score             REAL,
    cd_conta_anterior TEXT,              -- conta do filing anterior com a qual casou (ou o candidato, se ambiguo)
    PRIMARY KEY (cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_linha_id ON linha_empresa (cnpj_companhia, tipo_doc, linha_id);

CREATE TABLE IF NOT EXISTS linha_decisao (
    cnpj_companhia TEXT NOT NULL,
    tipo_doc       TEXT NOT NULL,
    cd_a           TEXT NOT NULL,
    data_a         TEXT NOT NULL,
    cd_b           TEXT NOT NULL,
    data_b         TEXT NOT NULL,
    decisao        TEXT NOT NULL CHECK (decisao IN ('mesma', 'diferente')),
    autor          TEXT,
    em             TEXT,
    PRIMARY KEY (cnpj_companhia, tipo_doc, cd_a, data_a, cd_b, data_b)
) WITHOUT ROWID;
"""


def encadear(colunas, ligacoes=None, bloqueados=None, reatar_por_pai=False, meta=None):
    """colunas = lista, em ordem cronológica, de {cd: (ds, st)}. Devolve lista de séries, cada uma
    {índice da coluna: cd}.

    ligacoes[i] = {cd nesta coluna: cd na anterior} tem precedência sobre o casamento calculado (o vínculo
    que a Camada 6 gravou, ou uma decisão 'mesma'). bloqueados = {(i, cd, cd_anterior)} impede o casamento
    automático (decisão 'diferente'). reatar_por_pai: depois de um buraco na série, reata também pelo
    (pai, nome normalizado), não só pelo (código, nome). meta, se dado, recebe
    meta[(i, cd)] = {casamento, score, anterior}."""
    series, dono, visto, visto_pai = [], {}, {}, {}
    for i, atual in enumerate(colunas):
        pronto = (ligacoes or {}).get(i) or {}
        calculado = match_filings(colunas[i - 1], atual) if i and len(pronto) < len(atual) else {}
        for cd, (ds, _st) in atual.items():
            anterior, como, score, candidato = pronto.get(cd), "camada6" if pronto.get(cd) else None, None, None
            if anterior is None:
                par = calculado.get(cd)
                if par and (i, cd, par[0]) in (bloqueados or ()):
                    par = None
                if par and par[1] == "ambiguo":
                    candidato, score = par[0], par[2]      # não encadeia: fica na fila de revisão
                elif par:
                    anterior, como, score = par[0], par[1], par[2]
            # séries que uma decisão 'diferente' proíbe para esta conta, também no reatamento por nome
            proibidas = {dono.get((i - 1, ant)) for (bi, bcd, ant) in (bloqueados or ()) if bi == i and bcd == cd}
            s = dono.get((i - 1, anterior)) if anterior is not None else None
            if s is not None and como is None:
                como = "estavel"
            nome = normalize_text(ds)
            if s is None:
                s = visto.get((cd, nome))
                if s is not None and (i in series[s] or s in proibidas):
                    s = None
                if s is not None:
                    como = "reatado"
            if s is None and reatar_por_pai:
                s = visto_pai.get((parent_code(cd), nome))
                if s is not None and (i in series[s] or s in proibidas):
                    s = None
                if s is not None:
                    como = "reatado_pai"
            if s is None:
                s = len(series)
                series.append({})
                como = "primeira" if i == 0 else ("ambiguo" if candidato is not None else "nova")
            series[s][i] = cd
            dono[(i, cd)] = s
            visto[(cd, nome)] = s
            visto_pai[(parent_code(cd), nome)] = s
            if meta is not None:
                meta[(i, cd)] = {"casamento": como, "score": score,
                                 "anterior": anterior if como not in ("primeira", "nova", "ambiguo", "reatado",
                                                                       "reatado_pai") else candidato}
    return series


def _linha_id(cnpj, tipo_doc, fonte, data, cd) -> str:
    return hashlib.sha1(f"{cnpj}|{tipo_doc}|{fonte}|{data}|{cd}".encode()).hexdigest()[:12]


def decisoes(conn, cnpj, tipo_doc):
    try:
        return conn.execute("SELECT cd_a, data_a, cd_b, data_b, decisao FROM linha_decisao "
                            "WHERE cnpj_companhia = ? AND tipo_doc = ?", (cnpj, tipo_doc)).fetchall()
    except sqlite3.OperationalError:
        return []


def linhas_da_empresa(df, cnpj, dec_por_tipo=None) -> list[tuple]:
    """df = latest_rows de uma empresa. Devolve as tuplas para inserir em linha_empresa."""
    out = []
    df = df[df["ordem_exercicio"] == "Último"]
    for tipo_doc, g in df.groupby("tipo_doc", sort=True):
        filings = sorted({(d, f) for d, f in zip(g["data_referencia"], g["fonte"])})
        colunas = [_linhas(g[(g["data_referencia"] == d) & (g["fonte"] == f)]) for d, f in filings]
        pos = {d: i for i, (d, _f) in enumerate(filings)}
        ligacoes, bloqueados = {}, set()
        for cd_a, data_a, cd_b, data_b, dec in (dec_por_tipo or {}).get(tipo_doc, []):
            ia, ib = pos.get(data_a), pos.get(data_b)
            if ia is None or ib is None or ib != ia + 1:
                continue
            if dec == "mesma":
                ligacoes.setdefault(ib, {})[cd_b] = cd_a
            else:
                bloqueados.add((ib, cd_b, cd_a))
        meta: dict = {}
        series = encadear(colunas, ligacoes, bloqueados, reatar_por_pai=True, meta=meta)
        for s in series:
            i0 = min(s)
            lid = _linha_id(cnpj, tipo_doc, filings[i0][1], filings[i0][0], s[i0])
            for i, cd in s.items():
                m = meta[(i, cd)]
                como = "decisao" if m["casamento"] == "camada6" and (i, cd) in {
                    (ib, c) for ib, mp in ligacoes.items() for c in mp} else m["casamento"]
                out.append((cnpj, tipo_doc, filings[i][1], filings[i][0], cd, lid, colunas[i][cd][0],
                            colunas[i][cd][1], como, m["score"], m["anterior"]))
    return out


def construir(conn, cnpj) -> int:
    df = latest_rows(conn, cnpj=cnpj)
    tipos = sorted(df["tipo_doc"].unique()) if not df.empty else []
    rows = linhas_da_empresa(df, cnpj, {t: decisoes(conn, cnpj, t) for t in tipos})
    conn.execute("DELETE FROM linha_empresa WHERE cnpj_companhia = ?", (cnpj,))
    conn.executemany("INSERT INTO linha_empresa VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def listar_ambiguos(conn, cnpj, tipo_doc=None):
    sql = ("SELECT tipo_doc, fonte, data_referencia, cd_conta, ds_conta, cd_conta_anterior, score "
           "FROM linha_empresa WHERE cnpj_companhia = ? AND casamento = 'ambiguo'")
    args = [cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        args.append(tipo_doc)
    return conn.execute(sql + " ORDER BY tipo_doc, data_referencia, cd_conta", args).fetchall()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cnpj")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--tipo-doc")
    ap.add_argument("--listar-ambiguos", action="store_true")
    ap.add_argument("--decidir", action="store_true")
    for a in ("de-cd", "de-data", "para-cd", "para-data", "autor"):
        ap.add_argument(f"--{a}")
    ap.add_argument("--decisao", choices=["mesma", "diferente"])
    args = ap.parse_args(argv)

    conn = get_db()
    conn.executescript(DDL)
    if args.listar_ambiguos:
        if not args.cnpj:
            ap.error("--listar-ambiguos exige --cnpj")
        for r in listar_ambiguos(conn, args.cnpj, args.tipo_doc):
            print(" | ".join("" if v is None else str(v) for v in r))
        return
    if args.decidir:
        falta = [a for a in ("cnpj", "tipo_doc", "de_cd", "de_data", "para_cd", "para_data", "decisao") if not getattr(args, a)]
        if falta:
            ap.error("--decidir exige " + ", ".join("--" + f.replace("_", "-") for f in falta))
        conn.execute("INSERT OR REPLACE INTO linha_decisao VALUES (?,?,?,?,?,?,?,?,?)",
                     (args.cnpj, args.tipo_doc, args.de_cd, args.de_data, args.para_cd, args.para_data,
                      args.decisao, args.autor, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
        print(f"decisão gravada; rode --cnpj {args.cnpj} para refazer as linhas dessa empresa")
        return
    if not args.cnpj and not args.full:
        ap.error("informe --cnpj ou --full")
    cnpjs = [args.cnpj] if args.cnpj else [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
    total = 0
    for i, cnpj in enumerate(cnpjs, 1):
        n = construir(conn, cnpj)
        total += n
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {n} linhas")
    print(f"linha_empresa: {total} linhas")


if __name__ == "__main__":
    main()
