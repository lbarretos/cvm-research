"""
Camada 5 — trilha temporal de linhas (check_type = 'text_stability'), com a
Camada 4 (similaridade textual, consistency_utils.text_similarity) embutida.

Para cada (cnpj, tipo_doc, fonte), percorre os filings em ordem de
data_referencia (ordem_exercicio = 'Último', versão máxima, uma linha por
código) e compara cada filing B com o anterior A, de cima para baixo na
hierarquia: os pais casados num nível definem quais conjuntos de filhos se
comparam no nível seguinte (um pai renumerado leva os filhos junto). Dentro de
cada pai:
  0. 'S' com o mesmo código dos dois lados → 'estavel' (código fixo pela CVM; não grava)
  1. mesmo normalize_text(ds_conta): mesmo código → 'estavel'; outro código → 'renumerado'
  2. sobras 'N' dos dois lados: pareamento guloso por maior text_similarity;
     score ≥ sim_alto → 'reformulacao'; sim_baixo < score < sim_alto → 'ambiguo'
     (fila de revisão: também vira flag layer 5 em consistency_flags)
  3. sobras de B → 'nova'; sobras de A → 'removida' ('S' nunca entra na similaridade)
Pai de A sem par em B → filhos 'removida'; pai de B sem par → filhos 'nova'.
Primeiro filing de cada sequência → 'primeira_ocorrencia' para todas as linhas.

Grava em cd_conta_ds_timeline (data_referencia = filing B; 'removida' com
cd_conta/ds_conta da linha antiga; cd_conta_anterior/ds_conta_anterior/
similarity_score quando há par) e em consistency_flags só os 'ambiguo'.
Linhas anteriores do mesmo (cnpj[, tipo_doc]) são apagadas nas duas tabelas
antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) depois da Camada 3. À mão
(na pasta scripts/analysis, .venv ativo):
  python check_text_stability.py --cnpj 84.429.695/0001-11
  python check_text_stability.py --cnpj 84.429.695/0001-11 --tipo-doc DFC_MI --sim-alto 0.8
  python check_text_stability.py --full          # base inteira (~145 empresas, ~2 min)
"""
import pandas as pd

from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows, new_run,
                               normalize_text, parent_code, text_similarity, write_flags)

LAYER = 5
CHECK_TYPE = "text_stability"
SIM_ALTO, SIM_BAIXO = 0.75, 0.45
CLASSES = ["primeira_ocorrencia", "estavel", "renumerado", "reformulacao", "ambiguo", "nova", "removida"]
TIMELINE_COLS = ["run_id", "cnpj_companhia", "tipo_doc", "cd_conta_pai", "ds_conta_norm", "fonte", "data_referencia",
                 "cd_conta", "ds_conta", "st_conta_fixa", "data_referencia_anterior", "cd_conta_anterior",
                 "ds_conta_anterior", "similarity_score", "classificacao"]


def _texto(v):
    return v if isinstance(v, str) else None


def _linhas(doc: pd.DataFrame) -> dict:
    """{cd_conta: (ds_conta, st_conta_fixa)} de um filing — uma entrada por código
    (a DRE do ITR repete o código por período)."""
    out: dict = {}
    for r in doc.itertuples(index=False):
        out.setdefault(r.cd_conta, (_texto(r.ds_conta), _texto(r.st_conta_fixa)))
    return out


def _row(cd: str, ds, st, classe: str, anterior=None, score=None) -> dict:
    return {"cd_conta": cd, "cd_conta_pai": parent_code(cd), "ds_conta": ds, "ds_conta_norm": normalize_text(ds),
            "st_conta_fixa": st, "cd_conta_anterior": anterior[0] if anterior else None,
            "ds_conta_anterior": anterior[1] if anterior else None, "similarity_score": score,
            "classificacao": classe}


def _comparar_pai(fa: dict, fb: dict, sim_alto: float, sim_baixo: float) -> tuple[list[dict], dict, int]:
    """fa/fb = {cd: (ds, st)}: filhos diretos de um pai em A e em B.
    Retorna (rows, mapa código A → código B das linhas casadas, n_estaveis)."""
    rows: list[dict] = []
    mapa: dict = {}
    estaveis = 0
    # 0. 'S' com o mesmo código: estável por definição da CVM
    for cd, (ds, st) in fa.items():
        if st == "S" and cd in fb and fb[cd][1] == "S":
            mapa[cd] = cd
            estaveis += 1
    # 1. nome normalizado
    na: dict = {}
    nb: dict = {}
    for cd, (ds, st) in fa.items():
        if cd not in mapa:
            na.setdefault(normalize_text(ds), []).append(cd)
    for cd, (ds, st) in fb.items():
        if cd not in mapa:
            nb.setdefault(normalize_text(ds), []).append(cd)
    sobra_a: list[str] = []
    sobra_b: list[str] = []
    for nome in list(na) + [k for k in nb if k not in na]:
        a, b = na.get(nome, []), nb.get(nome, [])
        comuns = [cd for cd in a if cd in b]
        for cd in comuns:
            mapa[cd] = cd
            estaveis += 1
        ra = [cd for cd in a if cd not in comuns]
        rb = [cd for cd in b if cd not in comuns]
        for x, y in zip(ra, rb):
            mapa[x] = y
            rows.append(_row(y, fb[y][0], fb[y][1], "renumerado", (x, fa[x][0]), 1.0))
        sobra_a += ra[len(rb):]
        sobra_b += rb[len(ra):]
    # 2. similaridade só entre linhas 'N'
    cand_a = [cd for cd in sobra_a if fa[cd][1] != "S"]
    cand_b = [cd for cd in sobra_b if fb[cd][1] != "S"]
    pares = sorted(((text_similarity(fa[x][0], fb[y][0]), x, y) for x in cand_a for y in cand_b),
                   key=lambda t: (-t[0], t[1], t[2]))
    usados_a: set = set()
    usados_b: set = set()
    for score, x, y in pares:
        if score <= sim_baixo:
            break
        if x in usados_a or y in usados_b:
            continue
        usados_a.add(x)
        usados_b.add(y)
        mapa[x] = y
        rows.append(_row(y, fb[y][0], fb[y][1], "reformulacao" if score >= sim_alto else "ambiguo",
                         (x, fa[x][0]), round(score, 4)))
    # 3. sobras
    for cd in sobra_b:
        if cd not in usados_b:
            rows.append(_row(cd, fb[cd][0], fb[cd][1], "nova"))
    for cd in sobra_a:
        if cd not in usados_a:
            rows.append(_row(cd, fa[cd][0], fa[cd][1], "removida", (cd, fa[cd][0])))
    return rows, mapa, estaveis


def _nivel(pai) -> tuple:
    return (-1, "") if pai is None else (pai.count("."), pai)


def compare_filings(A: dict, B: dict, sim_alto: float = SIM_ALTO, sim_baixo: float = SIM_BAIXO) -> tuple[list[dict], int]:
    """A/B = {cd: (ds, st)} de dois filings consecutivos. Retorna (rows sem contexto, n_estaveis).
    Processa os pais da raiz para as folhas; o mapa A→B dos pais já casados escolhe
    os filhos de A que correspondem a cada pai de B."""
    filhos_a: dict = {}
    filhos_b: dict = {}
    for cd, v in A.items():
        filhos_a.setdefault(parent_code(cd), {})[cd] = v
    for cd, v in B.items():
        filhos_b.setdefault(parent_code(cd), {})[cd] = v
    rows: list[dict] = []
    mapa: dict = {}
    consumidos: set = set()
    estaveis = 0
    for pb in sorted(filhos_b, key=_nivel):
        inverso = {v: k for k, v in mapa.items()}
        if pb in inverso:
            pa = inverso[pb]            # pai casado (estável ou renumerado) no nível acima
        elif pb in mapa:
            pa = None                   # o pai de A com esse código foi para outro lugar
        else:
            pa = pb                     # código literal (inclusive pais que não são linha, ex: '3')
        fa = filhos_a.get(pa, {}) if pa is not None and pa not in consumidos else {}
        if fa:
            consumidos.add(pa)
        r, m, n = _comparar_pai(fa, filhos_b[pb], sim_alto, sim_baixo)
        rows += r
        mapa.update(m)
        estaveis += n
    for pa, fa in filhos_a.items():
        if pa not in consumidos:
            rows += [_row(cd, ds, st, "removida", (cd, ds)) for cd, (ds, st) in fa.items()]
    return rows, estaveis


def check_text_stability(df: pd.DataFrame, sim_alto: float = SIM_ALTO,
                         sim_baixo: float = SIM_BAIXO) -> tuple[list[dict], list[dict], dict]:
    """df = saída de latest_rows. Retorna (rows da timeline, flags de 'ambiguo', stats).
    stats[tipo_doc] = {"filings": n, <classe>: n_linhas} (estavel contada, não gravada)."""
    rows: list[dict] = []
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return rows, flags, stats
    df = df[df["ordem_exercicio"] == "Último"]
    for (cnpj, tipo_doc, fonte), grupo in df.groupby(["cnpj_companhia", "tipo_doc", "fonte"], sort=True):
        st = stats.setdefault(tipo_doc, {"filings": 0, **{c: 0 for c in CLASSES}})
        anterior = None
        for data_ref in sorted(grupo["data_referencia"].unique()):
            atual = _linhas(grupo[grupo["data_referencia"] == data_ref])
            st["filings"] += 1
            contexto = {"cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "fonte": fonte, "data_referencia": data_ref}
            if anterior is None:
                novas = [_row(cd, ds, s, "primeira_ocorrencia") for cd, (ds, s) in atual.items()]
                rows += [{**contexto, "data_referencia_anterior": None, **r} for r in novas]
                st["primeira_ocorrencia"] += len(novas)
            else:
                data_ant, linhas_ant = anterior
                novas, estaveis = compare_filings(linhas_ant, atual, sim_alto, sim_baixo)
                st["estavel"] += estaveis
                for r in novas:
                    st[r["classificacao"]] += 1
                    rows.append({**contexto, "data_referencia_anterior": data_ant, **r})
                    if r["classificacao"] == "ambiguo":
                        flags.append({
                            "layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "ambiguo", "severity": "warn",
                            "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
                            "cd_conta": r["cd_conta"], "cd_conta_pai": r["cd_conta_pai"], "ds_conta": r["ds_conta"],
                            "fonte_ref": fonte, "data_ref": data_ant, "ordem_ref": "Último",
                            "fonte_cmp": fonte, "data_cmp": data_ref, "ordem_cmp": "Último",
                            "detalhe": {"score": r["similarity_score"], "cd_conta_anterior": r["cd_conta_anterior"],
                                        "ds_conta_anterior": r["ds_conta_anterior"]},
                        })
            anterior = (data_ref, atual)
    return rows, flags, stats


# ── Escrita ──────────────────────────────────────────────────────────────────

def clear_timeline(conn, cnpj: str, tipo_doc: str | None = None) -> int:
    sql = "DELETE FROM cd_conta_ds_timeline WHERE cnpj_companhia = ?"
    params: list = [cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        params.append(tipo_doc)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def write_timeline(conn, run_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = (f"INSERT INTO cd_conta_ds_timeline ({','.join(TIMELINE_COLS)}) "
           f"VALUES ({','.join('?' * len(TIMELINE_COLS))})")
    try:
        conn.executemany(sql, [tuple(run_id if c == "run_id" else r.get(c) for c in TIMELINE_COLS) for r in rows])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _escopo(args) -> str:
    if not args.cnpj and not args.tipo_doc and not args.desde and not args.ate:
        return "full"
    partes = [f"cnpj={args.cnpj}" if args.cnpj else None,
              f"tipo_doc={args.tipo_doc}" if args.tipo_doc else None,
              f"desde={args.desde}" if args.desde else None,
              f"ate={args.ate}" if args.ate else None]
    return " ".join(p for p in partes if p)


def main(argv=None) -> str:
    """Roda a Camada 5 e devolve o run_id. `argv=None` lê sys.argv."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--sim-alto", dest="sim_alto", type=float, default=SIM_ALTO,
                        help="score mínimo para 'reformulacao' (padrão 0.75)")
    parser.add_argument("--sim-baixo", dest="sim_baixo", type=float, default=SIM_BAIXO,
                        help="score máximo para 'nova'/'removida' (padrão 0.45); entre os dois é 'ambiguo'")
    args = parser.parse_args(argv)
    if not args.cnpj and not args.full:
        parser.error("informe --cnpj ou confirme a base inteira com --full")

    conn = get_db()
    if args.cnpj:
        cnpjs = [args.cnpj]
    else:
        cnpjs = [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
    run_id = new_run(conn, LAYER, CHECK_TYPE, _escopo(args), vars(args))
    print(f"run {run_id}: {len(cnpjs)} empresa(s), sim_alto={args.sim_alto} sim_baixo={args.sim_baixo}")

    total_checked = total_flagged = 0
    stats_total: dict = {}
    for i, cnpj in enumerate(cnpjs, 1):
        df = latest_rows(conn, cnpj=cnpj, tipo_doc=args.tipo_doc, desde=args.desde, ate=args.ate)
        rows, flags, stats = check_text_stability(df, args.sim_alto, args.sim_baixo)
        clear_timeline(conn, cnpj, args.tipo_doc)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_timeline(conn, run_id, rows)
        write_flags(conn, run_id, flags)
        filings = sum(s["filings"] for s in stats.values())
        total_checked += filings
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {filings} filings, {n} linhas na timeline, "
              f"{len(flags)} ambiguas")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (filings = documentos 'Último' por fonte; estavel não é gravada):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        print(f"  {tipo:7s} filings={s['filings']} " + " ".join(f"{c}={s[c]}" for c in CLASSES))
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
