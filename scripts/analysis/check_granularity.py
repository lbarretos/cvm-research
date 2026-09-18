"""
Camada 3 — granularidade entre filings (check_type = 'granularity').

Reaproveita os pares da Camada 2 (mesmo período, baseline × filing posterior;
check_cross_period.iter_pairs) e explica as linhas que existem só num dos lados
("exclusivas"), pai a pai, nesta ordem:
  1. nome   — mesmo ds_conta normalizado e mesmo st_conta_fixa dos dois lados
              → 'renumerado' (info; detalhe.casamento = 'nome', cd_ref, cd_cmp)
  2. zero   — |valor| < tol_abs (NULL = 0)            → 'zero_padding' (info)
  3. Outros — Σ exclusivas_ref − Σ exclusivas_cmp ≈ Σ Outros_cmp − Σ Outros_ref,
              contando as linhas "Outros"/"Demais" (consistency_utils.is_outros)
              entre os filhos do pai nos dois lados, comuns ou exclusivas
              → 'reclassificado_em_outros' (warn)
  4. valor  — exclusivas nos dois lados com Σ ref ≈ Σ cmp
              → 'renumerado' (info; detalhe.casamento = 'valor')
  5. irmão  — pai comum com pai_ref ≈ pai_cmp: o valor foi absorvido por um irmão
              nomeado → 'reclassificado_em_irmao' (warn; detalhe.irmaos_alterados)
  6. senão  — o valor saiu do pai (mudou de pai ou faz parte de uma reapresentação)
              → 'divergencia_nao_explicada' (error; detalhe.pai_ref/pai_cmp)
"≈" é |a − b| ≤ max(tol_abs, tol_rel × max(|a|, |b|)). Exclusivas cujo pai também é
exclusivo não geram flag (o pai é resolvido um nível acima); pai ausente dos dois
lados (ex: '3' na DRE) conta como raiz.

Saída: uma flag por linha exclusiva (valor_ref OU valor_cmp preenchido,
detalhe.exclusivo_em ∈ {'ref','cmp'}), ou por par casado por nome (cd_conta =
cd_ref, valor_ref e valor_cmp), mais uma flag-resumo por par com exclusivas
(cd_conta NULL; classificacao = classe mais grave; detalhe = contagens).
Flags anteriores do mesmo (cnpj[, tipo_doc]) são apagadas antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) depois da Camada 2. À mão
(na pasta scripts/analysis, .venv ativo):
  python check_granularity.py --cnpj 84.429.695/0001-11
  python check_granularity.py --cnpj 84.429.695/0001-11 --tipo-doc BPA --desde 2023
  python check_granularity.py --full             # base inteira (~145 empresas, ~2 min)
"""
import pandas as pd

from check_cross_period import iter_pairs
from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, is_outros, latest_rows,
                               new_run, normalize_text, parent_code, tolerancia, write_flags)

LAYER = 3
CHECK_TYPE = "granularity"
SEVERITY = {"renumerado": "info", "zero_padding": "info", "reclassificado_em_outros": "warn",
            "reclassificado_em_irmao": "warn", "divergencia_nao_explicada": "error"}
ORDEM_GRAVIDADE = ["divergencia_nao_explicada", "reclassificado_em_irmao", "reclassificado_em_outros",
                   "renumerado", "zero_padding"]
RESUMO_KEYS = ["linhas_exclusivas_ref", "linhas_exclusivas_cmp", "filhos_de_pai_exclusivo", *SEVERITY]


def _valor(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def _st(row):
    st = row.st_conta_fixa
    return None if st is None or (isinstance(st, float) and pd.isna(st)) else st


def _bate(a: float, b: float, tol_abs: float, tol_rel: float) -> bool:
    return abs(a - b) <= tolerancia(max(abs(a), abs(b)), tol_abs, tol_rel)


def _flag_linha(lado: str, cd: str, row, pai, classe: str, detalhe: dict) -> dict:
    val = _valor(row.vl_conta)
    return {
        "cd_conta": cd, "cd_conta_pai": pai, "ds_conta": row.ds_conta,
        "valor_ref": val if lado == "ref" else None,
        "valor_cmp": val if lado == "cmp" else None,
        "classificacao": classe, "severity": SEVERITY[classe],
        "detalhe": {"exclusivo_em": lado, **detalhe},
    }


def _resolver_pai(pai, ex_ref: list[str], ex_cmp: list[str], R: dict, C: dict,
                  tol_abs: float, tol_rel: float) -> list[dict]:
    """Exclusivas de UM pai (códigos em ex_ref só existem em R; ex_cmp só em C)."""
    flags: list[dict] = []

    # 1. nome (+ st_conta_fixa)
    nomes_ref: dict = {}
    nomes_cmp: dict = {}
    for cd in ex_ref:
        nomes_ref.setdefault((normalize_text(R[cd].ds_conta), _st(R[cd])), []).append(cd)
    for cd in ex_cmp:
        nomes_cmp.setdefault((normalize_text(C[cd].ds_conta), _st(C[cd])), []).append(cd)
    rest_ref: list[str] = []
    rest_cmp: list[str] = []
    for chave in list(nomes_ref) + [k for k in nomes_cmp if k not in nomes_ref]:
        a, b = nomes_ref.get(chave, []), nomes_cmp.get(chave, [])
        for cd_r, cd_c in zip(a, b):
            vr, vc = _valor(R[cd_r].vl_conta), _valor(C[cd_c].vl_conta)
            flags.append({
                "cd_conta": cd_r, "cd_conta_pai": pai, "ds_conta": R[cd_r].ds_conta,
                "valor_ref": vr, "valor_cmp": vc, "diff_abs": vc - vr,
                "diff_rel": (vc - vr) / abs(vr) if vr else None,
                "classificacao": "renumerado", "severity": SEVERITY["renumerado"],
                "detalhe": {"casamento": "nome", "cd_ref": cd_r, "cd_cmp": cd_c},
            })
        rest_ref += a[len(b):]
        rest_cmp += b[len(a):]

    # 2. zero
    restantes: list[tuple[str, str, object]] = []
    for lado, cds, docs in (("ref", rest_ref, R), ("cmp", rest_cmp, C)):
        for cd in cds:
            if abs(_valor(docs[cd].vl_conta)) < tol_abs:
                flags.append(_flag_linha(lado, cd, docs[cd], pai, "zero_padding", {}))
            else:
                restantes.append((lado, cd, docs[cd]))
    if not restantes:
        return flags

    soma_ref = sum(_valor(row.vl_conta) for lado, _, row in restantes if lado == "ref")
    soma_cmp = sum(_valor(row.vl_conta) for lado, _, row in restantes if lado == "cmp")
    extra = {"soma_exclusivos_ref": soma_ref, "soma_exclusivos_cmp": soma_cmp}

    # 3. Outros (linhas "Outros" dos dois lados, comuns ou exclusivas; ausente = 0)
    outros_ref = [cd for cd in R if parent_code(cd) == pai and is_outros(R[cd].ds_conta)]
    outros_cmp = [cd for cd in C if parent_code(cd) == pai and is_outros(C[cd].ds_conta)]
    if outros_ref or outros_cmp:
        o_ref = sum(_valor(R[cd].vl_conta) for cd in outros_ref)
        o_cmp = sum(_valor(C[cd].vl_conta) for cd in outros_cmp)
        nao_outros_ref = sum(_valor(row.vl_conta) for lado, cd, row in restantes if lado == "ref" and cd not in outros_ref)
        nao_outros_cmp = sum(_valor(row.vl_conta) for lado, cd, row in restantes if lado == "cmp" and cd not in outros_cmp)
        if _bate(nao_outros_ref - nao_outros_cmp, o_cmp - o_ref, tol_abs, tol_rel):
            det = {"soma_exclusivos_ref": nao_outros_ref, "soma_exclusivos_cmp": nao_outros_cmp,
                   "outros_ref": o_ref, "outros_cmp": o_cmp,
                   "cd_outros_ref": outros_ref, "cd_outros_cmp": outros_cmp}
            flags += [_flag_linha(lado, cd, row, pai, "reclassificado_em_outros", det) for lado, cd, row in restantes]
            return flags

    # 4. valor
    cds_ref = [cd for lado, cd, _ in restantes if lado == "ref"]
    cds_cmp = [cd for lado, cd, _ in restantes if lado == "cmp"]
    if cds_ref and cds_cmp and _bate(soma_ref, soma_cmp, tol_abs, tol_rel):
        det = {"casamento": "valor", "cd_ref": cds_ref, "cd_cmp": cds_cmp}
        flags += [_flag_linha(lado, cd, row, pai, "renumerado", det) for lado, cd, row in restantes]
        return flags

    # 5. irmão
    pai_ref = pai_cmp = None
    if pai is not None and pai in R and pai in C:
        pai_ref, pai_cmp = _valor(R[pai].vl_conta), _valor(C[pai].vl_conta)
        if _bate(pai_ref, pai_cmp, tol_abs, tol_rel):
            alterados = []
            for cd in R:
                if parent_code(cd) != pai or cd not in C:
                    continue
                vr, vc = _valor(R[cd].vl_conta), _valor(C[cd].vl_conta)
                if abs(vc - vr) > tolerancia(vr, tol_abs, tol_rel):
                    alterados.append({"cd": cd, "ref": vr, "cmp": vc})
            det = {**extra, "pai_ref": pai_ref, "pai_cmp": pai_cmp, "irmaos_alterados": alterados[:10]}
            flags += [_flag_linha(lado, cd, row, pai, "reclassificado_em_irmao", det) for lado, cd, row in restantes]
            return flags

    # 6. não explicada
    det = {**extra, "pai_ref": pai_ref, "pai_cmp": pai_cmp}
    flags += [_flag_linha(lado, cd, row, pai, "divergencia_nao_explicada", det) for lado, cd, row in restantes]
    return flags


def compare_granularity(ref: pd.DataFrame, cmp: pd.DataFrame,
                        tol_abs: float = 1000.0, tol_rel: float = 0.01) -> tuple[list[dict], dict]:
    """Linhas de UM período em dois documentos. Retorna (flags_de_linha, resumo)."""
    R = {r.cd_conta: r for r in ref.itertuples(index=False)}
    C = {r.cd_conta: r for r in cmp.itertuples(index=False)}
    ex_ref = [cd for cd in R if cd not in C]
    ex_cmp = [cd for cd in C if cd not in R]
    resumo = {k: 0 for k in RESUMO_KEYS}
    resumo["linhas_exclusivas_ref"], resumo["linhas_exclusivas_cmp"] = len(ex_ref), len(ex_cmp)
    flags: list[dict] = []
    if not ex_ref and not ex_cmp:
        return flags, resumo
    exclusivos = set(ex_ref) | set(ex_cmp)
    por_pai: dict = {}
    for cd in ex_ref:
        por_pai.setdefault(parent_code(cd), ([], []))[0].append(cd)
    for cd in ex_cmp:
        por_pai.setdefault(parent_code(cd), ([], []))[1].append(cd)
    for pai, (er, ec) in por_pai.items():
        if pai is not None and pai in exclusivos:
            resumo["filhos_de_pai_exclusivo"] += len(er) + len(ec)
            continue
        flags.extend(_resolver_pai(pai, er, ec, R, C, tol_abs, tol_rel))
    for f in flags:
        resumo[f["classificacao"]] += 1
    return flags, resumo


def check_granularity(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"pares": n, "pares_com_exclusivos": m, <classe>: n_flags_de_linha}.
    """
    flags: list[dict] = []
    stats: dict = {}
    for par, ref, cmp in iter_pairs(df):
        tipo_doc = par["tipo_doc"]
        st = stats.setdefault(tipo_doc, {"pares": 0, "pares_com_exclusivos": 0, **{c: 0 for c in SEVERITY}})
        st["pares"] += 1
        linhas, resumo = compare_granularity(ref, cmp, tol_abs, tol_rel)
        if not linhas:
            continue
        st["pares_com_exclusivos"] += 1
        for c in SEVERITY:
            st[c] += resumo[c]
        contexto = {"layer": LAYER, "check_type": CHECK_TYPE, **par}
        flags.extend({**contexto, **linha} for linha in linhas)
        classe = next(c for c in ORDEM_GRAVIDADE if resumo[c])
        flags.append({**contexto, "cd_conta": None, "classificacao": classe, "severity": SEVERITY[classe],
                      "detalhe": {k: resumo[k] for k in RESUMO_KEYS}})
    return flags, stats


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
    """Roda a Camada 3 e devolve o run_id. `argv=None` lê sys.argv."""
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
        df = latest_rows(conn, cnpj=cnpj, tipo_doc=args.tipo_doc, desde=args.desde, ate=args.ate)
        flags, stats = check_granularity(df, args.tol_abs, args.tol_rel)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_flags(conn, run_id, flags)
        pares = sum(s["pares"] for s in stats.values())
        total_checked += pares
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {pares} pares, {n} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (pares = documento_ref × documento_cmp × período):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        classes = " ".join(f"{c}={s[c]}" for c in SEVERITY)
        print(f"  {tipo:7s} pares={s['pares']} com_exclusivos={s['pares_com_exclusivos']} {classes}")
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
