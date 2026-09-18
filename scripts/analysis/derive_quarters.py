"""
Camada 6 — desacúmulo (check_type = 'derive_quarters') → demonstrativos_trimestrais.

Para cada (cnpj, tipo_doc ∈ {DRE, DFC_MI, DVA}, safra):
  - safra 'original'      = colunas ordem_exercicio = 'Último' de cada filing;
  - safra 'reapresentado' = colunas 'Penúltimo' dos filings do exercício seguinte.
Os dois operandos de um derivado vêm SEMPRE da mesma safra.

Em cada documento, o acumulado é a linha com menor dt_ini_exerc; o trimestre é a
duração do acumulado (3/6/9/12 meses → 1..4), o que também resolve exercício
social fora do calendário. Documento com outra duração (ou DFP que não é o 4T)
é irregular e não entra. Por exercício (exercicio_ini) e trimestre n:
  - vl_publicado : DRE 1T–3T, linha trimestral isolada do ITR (dt_ini = início do trimestre)
  - vl_derivado  : n = 1 → acum(1T); n > 1 → acum(Qn) − acum(Qn−1); n = 4 → DFP − acum(3T)
  - vl_final     : publicado quando existe (origem 'publicado'), senão derivado
Flags (uma por linha; precedência nesta ordem):
  - 'reapresentacao_intra_ano' (warn): |publicado − derivado| > tolerância; na DFC,
    6.05 derivado do 4T ≠ variação do saldo final (6.05.02 DFP − 6.05.02 3T; reserva:
    BPA 1.01.01 na safra original) — também vira flag de linha em consistency_flags
  - 'linha_sem_par' (info): conta ausente do acumulado anterior (não deriva)
  - 'sem_anterior' / 'sem_3t' (info): não há acumulado anterior (2T/3T; 4T)
  - 'componente_reapresentado' (info): minuendo ou subtraendo aparece num resumo
    'reapresentacao' da Camada 2 (consistency_flags layer 2)
  - 'sem_dfp': 3T sem DFP — só flag-resumo em consistency_flags (não há linha de 4T)
3.99 (lucro por ação) e descendentes ficam fora: LPA não é aditivo.
Flags-resumo por trimestre (cd_conta NULL) em consistency_flags para
componente_reapresentado / sem_anterior / sem_3t / sem_dfp. Linhas anteriores do
mesmo (cnpj[, tipo_doc]) são apagadas nas duas tabelas antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) depois da Camada 5. À mão
(na pasta scripts/analysis, .venv ativo):
  python derive_quarters.py --cnpj 84.429.695/0001-11
  python derive_quarters.py --cnpj 84.429.695/0001-11 --tipo-doc DRE --desde 2020
  python derive_quarters.py --full               # base inteira (~145 empresas)
"""
from datetime import date

import pandas as pd

from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows, new_run,
                               parent_code, tolerancia, write_flags)

LAYER = 6
CHECK_TYPE = "derive_quarters"
TIPOS = ["DRE", "DFC_MI", "DVA"]
SAFRAS = {"original": "Último", "reapresentado": "Penúltimo"}
SEVERITY = {"reapresentacao_intra_ano": "warn", "componente_reapresentado": "info", "linha_sem_par": "info",
            "sem_anterior": "info", "sem_3t": "info", "sem_dfp": "info"}
SKIP_PREFIX = "3.99"
COLS = ["run_id", "cnpj_companhia", "tipo_doc", "safra", "exercicio_ini", "dt_ini_exerc", "dt_fim_exerc", "trimestre",
        "cd_conta", "ds_conta", "vl_publicado", "vl_derivado", "origem", "vl_final", "flag",
        "fonte_a", "data_a", "ordem_a", "fonte_b", "data_b", "ordem_b"]


# ── calendário ───────────────────────────────────────────────────────────────

def meses(ini: str, fim: str) -> int:
    """Meses cobertos por [ini, fim]: 2024-01-01..2024-03-31 → 3."""
    a, b = date.fromisoformat(ini), date.fromisoformat(fim)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def trimestre_de(ini: str, fim: str):
    """Posição do acumulado no exercício social (1..4) ou None se a duração não é 3/6/9/12 meses."""
    m = meses(ini, fim)
    return m // 3 if m in (3, 6, 9, 12) else None


def inicio_trimestre(exercicio_ini: str, n: int) -> str:
    """Primeiro dia do trimestre n do exercício que começa em exercicio_ini."""
    y, m = int(exercicio_ini[:4]), int(exercicio_ini[5:7]) + 3 * (n - 1)
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


# ── leitura dos documentos ───────────────────────────────────────────────────

def _valor(v):
    return 0.0 if v is None or pd.isna(v) else float(v)


def _texto(v):
    return v if isinstance(v, str) else None


def docs_acumulados(dd: pd.DataFrame) -> tuple[dict, int]:
    """dd = linhas de um (tipo_doc, ordem_exercicio). Retorna ({(exercicio_ini, n): doc}, irregulares).
    doc = {"fonte", "data", "ordem", "ini", "fim", "acum": {cd: (ds, vl)}, "tri": {cd: vl}} — tri só
    tem as linhas de período curto (dt_ini > exercicio_ini), i.e. o trimestre isolado da DRE."""
    docs: dict = {}
    irregulares = 0
    for (fonte, data_ref, ordem), g in dd.groupby(["fonte", "data_referencia", "ordem_exercicio"], sort=True):
        g = g[g["periodo_ini"] != "NA"]
        if g.empty:
            continue
        ini, fim = g["periodo_ini"].min(), g["periodo_fim"].iloc[0]
        n = trimestre_de(ini, fim)
        if n is None or (fonte == "DFP") != (n == 4):
            irregulares += 1
            continue
        acum = {}
        tri = {}
        for r in g.itertuples(index=False):
            if r.cd_conta.startswith(SKIP_PREFIX):
                continue
            if r.periodo_ini == ini:
                acum.setdefault(r.cd_conta, (_texto(r.ds_conta), r.vl_conta))
            else:
                tri.setdefault(r.cd_conta, r.vl_conta)
        docs[(ini, n)] = {"fonte": fonte, "data": data_ref, "ordem": ordem, "ini": ini, "fim": fim, "acum": acum, "tri": tri}
    return docs, irregulares


def _chave(tipo_doc: str, doc: dict) -> tuple:
    return (tipo_doc, doc["fonte"], doc["data"], doc["ordem"], doc["ini"], doc["fim"])


def _saldo_caixa(doc: dict, bpa: dict, safra: str):
    """Referência de caixa no fim do período de `doc`: 6.05.02 da própria DFC ou, na safra
    original, 1.01.01 do BPA com o mesmo dt_fim. Retorna (valor, 'saldo_final'|'bpa_caixa') ou (None, None)."""
    if "6.05.02" in doc["acum"]:
        return _valor(doc["acum"]["6.05.02"][1]), "saldo_final"
    if safra == "original" and doc["fim"] in bpa:
        return bpa[doc["fim"]], "bpa_caixa"
    return None, None


# ── derivação ────────────────────────────────────────────────────────────────

def _flag_linha(cnpj, tipo_doc, cd, ds, ini_q, fim_q, a, b, valor_ref, valor_cmp, detalhe) -> dict:
    return {
        "layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "reapresentacao_intra_ano", "severity": "warn",
        "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": cd, "cd_conta_pai": parent_code(cd), "ds_conta": ds,
        "periodo_ini": ini_q, "periodo_fim": fim_q,
        "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
        "fonte_cmp": b["fonte"] if b else None, "data_cmp": b["data"] if b else None, "ordem_cmp": b["ordem"] if b else None,
        "valor_ref": valor_ref, "valor_cmp": valor_cmp, "diff_abs": valor_cmp - valor_ref,
        "diff_rel": (valor_cmp - valor_ref) / abs(valor_ref) if valor_ref else None,
        "detalhe": detalhe,
    }


def _derivar_exercicio(cnpj, tipo_doc, safra, exercicio_ini, qs: dict, bpa: dict, reapresentados: set,
                       tol_abs, tol_rel) -> tuple[list[dict], list[dict], dict]:
    """qs = {n: doc} de um exercício. Retorna (linhas, flags, contagens por flag)."""
    rows: list[dict] = []
    flags: list[dict] = []
    cont = {k: 0 for k in SEVERITY}
    for n in sorted(qs):
        a = qs[n]
        b = qs.get(n - 1) if n > 1 else None
        ini_q, fim_q = inicio_trimestre(exercicio_ini, n), a["fim"]
        falta = None if (n == 1 or b is not None) else ("sem_3t" if n == 4 else "sem_anterior")
        componente = _chave(tipo_doc, a) in reapresentados or (b is not None and _chave(tipo_doc, b) in reapresentados)
        docs_ab = {"fonte_a": a["fonte"], "data_a": a["data"], "ordem_a": a["ordem"],
                   "fonte_b": b["fonte"] if b else None, "data_b": b["data"] if b else None, "ordem_b": b["ordem"] if b else None}
        base = {"cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "safra": safra, "exercicio_ini": exercicio_ini,
                "dt_ini_exerc": ini_q, "dt_fim_exerc": fim_q, "trimestre": n, **docs_ab}
        detalhe = {"safra": safra, "trimestre": n, "exercicio_ini": exercicio_ini}
        linhas_q: list[dict] = []
        for cd, (ds, va) in a["acum"].items():
            if n == 1:
                pub = _valor(va) if tipo_doc == "DRE" else None
                der = _valor(va)
                flag = None
            else:
                pub = _valor(a["tri"][cd]) if tipo_doc == "DRE" and n < 4 and cd in a["tri"] else None
                if falta:
                    der, flag = None, falta
                elif cd not in b["acum"]:
                    der, flag = None, "linha_sem_par"
                else:
                    der, flag = _valor(va) - _valor(b["acum"][cd][1]), None
            if pub is not None and der is not None and abs(pub - der) > tolerancia(pub, tol_abs, tol_rel):
                flag = "reapresentacao_intra_ano"
                flags.append(_flag_linha(cnpj, tipo_doc, cd, ds, ini_q, fim_q, a, b, pub, der, detalhe))
            elif flag is None and componente:
                flag = "componente_reapresentado"
            linhas_q.append({**base, "cd_conta": cd, "ds_conta": ds, "vl_publicado": pub, "vl_derivado": der,
                             "origem": "publicado" if pub is not None else "derivado",
                             "vl_final": pub if pub is not None else der, "flag": flag})
        # DFC 4T: 6.05 derivado × variação do saldo final de caixa
        if tipo_doc == "DFC_MI" and n == 4 and b is not None:
            linha = next((l for l in linhas_q if l["cd_conta"] == "6.05" and l["vl_derivado"] is not None), None)
            if linha:
                cx_a, modo = _saldo_caixa(a, bpa, safra)
                cx_b, modo_b = _saldo_caixa(b, bpa, safra)
                if cx_a is not None and cx_b is not None and modo == modo_b:
                    ref = cx_a - cx_b
                    if abs(linha["vl_derivado"] - ref) > tolerancia(linha["vl_derivado"], tol_abs, tol_rel):
                        linha["flag"] = "reapresentacao_intra_ano"
                        flags.append(_flag_linha(cnpj, tipo_doc, "6.05", linha["ds_conta"], ini_q, fim_q, a, b,
                                                 linha["vl_derivado"], ref, {**detalhe, "verificacao": modo}))
        for l in linhas_q:
            if l["flag"]:
                cont[l["flag"]] += 1
        # flags-resumo do trimestre
        for classe in ("sem_anterior", "sem_3t", "componente_reapresentado"):
            k = sum(1 for l in linhas_q if l["flag"] == classe)
            if k:
                flags.append({"layer": LAYER, "check_type": CHECK_TYPE, "classificacao": classe, "severity": SEVERITY[classe],
                              "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": None,
                              "periodo_ini": ini_q, "periodo_fim": fim_q,
                              "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
                              "fonte_cmp": docs_ab["fonte_b"], "data_cmp": docs_ab["data_b"], "ordem_cmp": docs_ab["ordem_b"],
                              "detalhe": {**detalhe, "linhas": k}})
        rows += linhas_q
    if 3 in qs and 4 not in qs:
        a = qs[3]
        cont["sem_dfp"] += 1
        flags.append({"layer": LAYER, "check_type": CHECK_TYPE, "classificacao": "sem_dfp", "severity": "info",
                      "cnpj_companhia": cnpj, "tipo_doc": tipo_doc, "cd_conta": None,
                      "periodo_ini": exercicio_ini, "periodo_fim": a["fim"],
                      "fonte_ref": a["fonte"], "data_ref": a["data"], "ordem_ref": a["ordem"],
                      "detalhe": {"safra": safra, "trimestre": 4, "exercicio_ini": exercicio_ini}})
    return rows, flags, cont


def derive_quarters(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01,
                    reapresentados: set | None = None) -> tuple[list[dict], list[dict], dict]:
    """df = saída de latest_rows (pode incluir BPA, usado só na checagem de caixa).
    Retorna (linhas de demonstrativos_trimestrais, flags, stats[tipo_doc])."""
    rows: list[dict] = []
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return rows, flags, stats
    reapresentados = reapresentados or set()
    for cnpj, dfc in df.groupby("cnpj_companhia", sort=True):
        for tipo_doc in TIPOS:
            d = dfc[dfc["tipo_doc"] == tipo_doc]
            if d.empty:
                continue
            st = stats.setdefault(tipo_doc, {"exercicios": 0, "trimestres": 0, "linhas": 0, "docs_irregulares": 0,
                                             **{k: 0 for k in SEVERITY}})
            for safra, ordem in SAFRAS.items():
                docs, irregulares = docs_acumulados(d[d["ordem_exercicio"] == ordem])
                st["docs_irregulares"] += irregulares
                b = dfc[(dfc["tipo_doc"] == "BPA") & (dfc["ordem_exercicio"] == ordem) & (dfc["cd_conta"] == "1.01.01")]
                bpa = {r.periodo_fim: _valor(r.vl_conta) for r in b.itertuples(index=False)}
                exercicios: dict = {}
                for (ini, n), doc in docs.items():
                    exercicios.setdefault(ini, {})[n] = doc
                for exercicio_ini in sorted(exercicios):
                    qs = exercicios[exercicio_ini]
                    r, f, cont = _derivar_exercicio(cnpj, tipo_doc, safra, exercicio_ini, qs, bpa, reapresentados, tol_abs, tol_rel)
                    st["exercicios"] += 1
                    st["trimestres"] += len(qs)
                    st["linhas"] += len(r)
                    for k, v in cont.items():
                        st[k] += v
                    rows += r
                    flags += f
    return rows, flags, stats


# ── banco ────────────────────────────────────────────────────────────────────

def reapresentados_camada2(conn, cnpj: str) -> set:
    """Documentos (dos dois lados) dos resumos 'reapresentacao' da Camada 2 para a empresa."""
    out = set()
    for r in conn.execute("""SELECT tipo_doc, fonte_ref, data_ref, ordem_ref, fonte_cmp, data_cmp, ordem_cmp, periodo_ini, periodo_fim
                             FROM consistency_flags WHERE layer = 2 AND cd_conta IS NULL AND classificacao = 'reapresentacao'
                               AND cnpj_companhia = ?""", (cnpj,)):
        tipo, fr, dr, orr, fc, dc, oc, pi, pf = r
        out.add((tipo, fr, dr, orr, pi, pf))
        out.add((tipo, fc, dc, oc, pi, pf))
    return out


def clear_trimestrais(conn, cnpj: str, tipo_doc: str | None = None) -> int:
    sql = "DELETE FROM demonstrativos_trimestrais WHERE cnpj_companhia = ?"
    params: list = [cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        params.append(tipo_doc)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def write_trimestrais(conn, run_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = f"INSERT INTO demonstrativos_trimestrais ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})"
    try:
        conn.executemany(sql, [tuple(run_id if c == "run_id" else r.get(c) for c in COLS) for r in rows])
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
    """Roda a Camada 6 e devolve o run_id. `argv=None` lê sys.argv."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args(argv)
    if not args.cnpj and not args.full:
        parser.error("informe --cnpj ou confirme a base inteira com --full")

    conn = get_db()
    if args.cnpj:
        cnpjs = [args.cnpj]
    else:
        cnpjs = [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
    run_id = new_run(conn, LAYER, CHECK_TYPE, _escopo(args), vars(args))
    print(f"run {run_id}: {len(cnpjs)} empresa(s), tol_abs={args.tol_abs} tol_rel={args.tol_rel}")

    total_checked = total_flagged = 0
    stats_total: dict = {}
    for i, cnpj in enumerate(cnpjs, 1):
        df = latest_rows(conn, cnpj=cnpj, desde=args.desde, ate=args.ate)
        if args.tipo_doc:
            df = df[df["tipo_doc"].isin([args.tipo_doc, "BPA"])]
        rows, flags, stats = derive_quarters(df, args.tol_abs, args.tol_rel, reapresentados_camada2(conn, cnpj))
        clear_trimestrais(conn, cnpj, args.tipo_doc)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_trimestrais(conn, run_id, rows)
        write_flags(conn, run_id, flags)
        trimestres = sum(s["trimestres"] for s in stats.values())
        total_checked += trimestres
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {trimestres} trimestres, {n} linhas trimestrais, {len(flags)} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (trimestres = exercício × trimestre × safra):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        print(f"  {tipo:7s} exercicios={s['exercicios']} trimestres={s['trimestres']} linhas={s['linhas']} "
              f"irregulares={s['docs_irregulares']} " + " ".join(f"{k}={s[k]}" for k in SEVERITY))
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
