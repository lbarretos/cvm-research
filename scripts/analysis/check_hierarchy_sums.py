"""
Camada 1 — soma hierárquica intra-documento (check_type = 'hierarchy_sum').

Dentro de cada (documento, ordem_exercicio, período) na versão máxima, verifica
se cada conta-pai presente é igual à soma dos filhos diretos e se as fórmulas
fixas de nível 2 (DRE e DFC_MI, só fora do setor Financeiro) fecham. É o teste
de regressão da ingestão: uma falha aqui é sintoma de documento parcial ou de
período misturado, não de reapresentação (isso é a Camada 2).

Classificação por pai (tolerância |Σ filhos − pai| ≤ max(tol_abs, tol_rel × |pai|), NULL = 0):
  - bate                                         → sem flag
  - pai ≠ 0 e todos os filhos 0/NULL             → 'nao_detalhado' (info)
  - pai 0/NULL e algum filho ≠ 0                 → 'pai_vazio' (warn)
  - pai ≠ 0, filhos ≠ 0, diferença > tolerância  → 'divergencia' (error)
  - fórmula de nível 2 não fecha                 → 'divergencia_formula' (error)
Exceções (consistency_utils.EXCECOES_SOMA): DFC_MI 6.05 = 6.05.02 − 6.05.01
('saldo'); DRE 3.99 e descendentes ignorados ('skip'). Filho sem pai no
documento (ex: 3.01 — a DRE não tem conta '3') não é checado.

Cada flag guarda o documento em fonte_ref/data_ref/ordem_ref (fonte_cmp/data_cmp
ficam NULL), valor_ref = pai, valor_cmp = soma (ou saldo, ou soma da fórmula),
diff_abs = valor_cmp − valor_ref e detalhe = {regra, filhos, filhos_nao_zero} ou
{regra: 'formula', formula, termos}. Flags anteriores do mesmo (cnpj[, tipo_doc])
são apagadas antes de gravar.

Roda no job semanal (scripts/update_weekly.sh) logo após ingest_dfp/ingest_itr,
na base inteira. À mão (na pasta scripts/analysis, .venv ativo):
  python check_hierarchy_sums.py --cnpj 84.429.695/0001-11
  python check_hierarchy_sums.py --cnpj 84.429.695/0001-11 --tipo-doc DRE --desde 2023
  python check_hierarchy_sums.py --full          # base inteira (~145 empresas)
"""
import pandas as pd

from consistency_utils import (EXCECOES_SOMA, FORMULAS_NIVEL2, add_common_args, clear_flags,
                               cnpjs_financeiros, finish_run, get_db, latest_rows, new_run,
                               parent_code, parse_hierarchy, tolerancia, write_flags)

LAYER = 1
CHECK_TYPE = "hierarchy_sum"
SEVERITY = {"nao_detalhado": "info", "pai_vazio": "warn",
            "divergencia": "error", "divergencia_formula": "error"}
GROUP_COLS = ["cnpj_companhia", "tipo_doc", "fonte", "data_referencia", "ordem_exercicio",
              "periodo_ini", "periodo_fim"]


def _valor(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def _classificar(pai: float, soma: float, filhos_nao_zero: int, tol_abs: float, tol_rel: float):
    """Classe da falha ou None quando bate. `pai` já com NULL = 0."""
    if abs(soma - pai) <= tolerancia(pai, tol_abs, tol_rel):
        return None
    if pai != 0 and filhos_nao_zero == 0:
        return "nao_detalhado"
    if pai == 0:
        return "pai_vazio"
    return "divergencia"


def _flag(cd: str, ds, pai: float, soma: float, classe: str, detalhe: dict) -> dict:
    return {
        "cd_conta": cd,
        "cd_conta_pai": parent_code(cd),
        "ds_conta": None if ds is None or pd.isna(ds) else ds,
        "valor_ref": pai,
        "valor_cmp": soma,
        "diff_abs": soma - pai,
        "diff_rel": (soma - pai) / abs(pai) if pai else None,
        "classificacao": classe,
        "severity": SEVERITY[classe],
        "detalhe": detalhe,
    }


def _ignorado(cd: str, skips: list[str]) -> bool:
    return any(cd == s or cd.startswith(s + ".") for s in skips)


def check_document(doc: pd.DataFrame, tipo_doc: str, tol_abs: float = 1000.0,
                   tol_rel: float = 0.01, formulas: bool = True) -> tuple[list[dict], int]:
    """Linhas de UM (documento, ordem_exercicio, período). Retorna (flags, n_checados):
    flags só com os campos da linha (o chamador acrescenta o contexto); n_checados
    = pais verificados + fórmulas verificadas."""
    valores = dict(zip(doc["cd_conta"], doc["vl_conta"]))
    nomes = dict(zip(doc["cd_conta"], doc["ds_conta"]))
    skips = [cd for (t, cd), regra in EXCECOES_SOMA.items() if t == tipo_doc and regra == "skip"]
    flags: list[dict] = []
    checados = 0

    for pai, filhos in parse_hierarchy(valores).items():
        if _ignorado(pai, skips):
            continue
        regra = EXCECOES_SOMA.get((tipo_doc, pai), "soma")
        vals = {cd: _valor(valores[cd]) for cd in filhos}
        if regra == "saldo":
            soma = vals.get(f"{pai}.02", 0.0) - vals.get(f"{pai}.01", 0.0)
        else:
            soma = sum(vals.values())
        pai_v = _valor(valores[pai])
        nao_zero = sum(1 for v in vals.values() if v != 0)
        checados += 1
        classe = _classificar(pai_v, soma, nao_zero, tol_abs, tol_rel)
        if classe:
            flags.append(_flag(pai, nomes[pai], pai_v, soma, classe,
                               {"regra": regra, "filhos": filhos, "filhos_nao_zero": nao_zero}))

    if formulas:
        for alvo, termos in FORMULAS_NIVEL2.get(tipo_doc, []):
            if alvo not in valores:
                continue
            checados += 1
            pai_v = _valor(valores[alvo])
            valores_termos = {t: _valor(valores.get(t)) for t in termos}
            soma = sum(valores_termos.values())
            if abs(soma - pai_v) > tolerancia(pai_v, tol_abs, tol_rel):
                flags.append(_flag(alvo, nomes[alvo], pai_v, soma, "divergencia_formula",
                                   {"regra": "formula", "formula": f"{alvo} = {' + '.join(termos)}",
                                    "termos": valores_termos}))
    return flags, checados


def check_hierarchy_sums(df: pd.DataFrame, tol_abs: float = 1000.0, tol_rel: float = 0.01,
                         formulas: bool = True) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"grupos": n, "pais": n_checados, <classe>: n_flags, ...},
    contando grupos (documento, ordem_exercicio, período).
    Linhas com periodo_fim NULL são ignoradas (groupby descarta NaN na chave).
    """
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return flags, stats
    for (cnpj, tipo_doc, fonte, data_ref, ordem, p_ini, p_fim), grupo in df.groupby(GROUP_COLS, sort=True):
        linhas, checados = check_document(grupo, tipo_doc, tol_abs, tol_rel, formulas)
        st = stats.setdefault(tipo_doc, {"grupos": 0, "pais": 0, **{c: 0 for c in SEVERITY}})
        st["grupos"] += 1
        st["pais"] += checados
        for linha in linhas:
            st[linha["classificacao"]] += 1
        contexto = {
            "layer": LAYER, "check_type": CHECK_TYPE,
            "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
            "periodo_ini": p_ini, "periodo_fim": p_fim,
            "fonte_ref": fonte, "data_ref": data_ref, "ordem_ref": ordem,
        }
        flags.extend({**contexto, **linha} for linha in linhas)
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
    """Roda a Camada 1 e devolve o run_id. `argv=None` lê sys.argv."""
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
    financeiros = cnpjs_financeiros(conn)
    run_id = new_run(conn, LAYER, CHECK_TYPE, _escopo(args), vars(args))
    print(f"run {run_id}: {len(cnpjs)} empresa(s), tol_abs={args.tol_abs} tol_rel={args.tol_rel}, "
          f"{len(financeiros)} sem fórmulas de nível 2 (setor Financeiro)")

    total_checked = total_flagged = 0
    stats_total: dict = {}
    for i, cnpj in enumerate(cnpjs, 1):
        df = latest_rows(conn, cnpj=cnpj, tipo_doc=args.tipo_doc, desde=args.desde, ate=args.ate)
        flags, stats = check_hierarchy_sums(df, args.tol_abs, args.tol_rel, formulas=cnpj not in financeiros)
        clear_flags(conn, LAYER, CHECK_TYPE, cnpj, args.tipo_doc)
        n = write_flags(conn, run_id, flags)
        pais = sum(s["pais"] for s in stats.values())
        total_checked += pais
        total_flagged += n
        for tipo, s in stats.items():
            acc = stats_total.setdefault(tipo, {k: 0 for k in s})
            for k in acc:
                acc[k] += s[k]
        print(f"  [{i}/{len(cnpjs)}] {cnpj}: {len(df)} linhas, {pais} pais/fórmulas, {n} flags")

    finish_run(conn, run_id, total_checked, total_flagged)
    print("\nResumo por tipo_doc (grupos = documento × ordem × período):")
    for tipo in sorted(stats_total):
        s = stats_total[tipo]
        classes = " ".join(f"{c}={s[c]}" for c in SEVERITY)
        print(f"  {tipo:7s} grupos={s['grupos']} pais={s['pais']} {classes}")
    print(f"total_checked={total_checked} total_flagged={total_flagged}")
    return run_id


if __name__ == "__main__":
    main()
