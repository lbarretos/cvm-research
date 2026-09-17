"""
Camada 2 — cruzamento entre filings (check_type = 'cross_period').

O mesmo período contábil aparece em até 5 filings: o BPA de 31/12/Y está no
DFP(Y).Último, nos ITRs 1T/2T/3T(Y+1).Penúltimo e no DFP(Y+1).Penúltimo; a
DRE do 2T de Y (trimestre e acumulado, dt_ini_exerc distinto) está no
ITR 2T(Y).Último e no ITR 2T(Y+1).Penúltimo.

Esta camada agrupa as linhas por (cnpj, tipo_doc, periodo_ini, periodo_fim),
toma como baseline o filing de menor data_referencia (o original, como
reportado na época) e compara cada filing posterior ao baseline — nunca
filings posteriores entre si.

Classificação do PAR (documento_ref, documento_cmp, período), pela conta-total
do tipo_doc (consistency_utils.total_codes):
  - total diverge acima da tolerância → 'reapresentacao' (warn); toda linha
    divergente do par herda a classe;
  - totais batem e alguma linha diverge → 'reclassificacao' (info);
  - linha que existe só num lado não gera flag aqui (Camada 3, Fase 3); entra
    apenas nas contagens do resumo do par.
Tolerância por linha: |cmp − ref| > max(tol_abs, tol_rel × |ref|); NULL = 0.

Saída: uma flag por linha divergente + uma flag-resumo por par (cd_conta NULL)
com detalhe = {linhas_comuns, linhas_divergentes, linhas_exclusivas_ref,
linhas_exclusivas_cmp, total_disponivel}. Pares sem linha divergente não geram
flag. Flags anteriores do mesmo (cnpj[, tipo_doc]) são apagadas antes de gravar.

Uso (na pasta scripts/analysis, .venv ativo):
  python check_cross_period.py --cnpj 84.429.695/0001-11
  python check_cross_period.py --cnpj 84.429.695/0001-11 --tipo-doc BPA --desde 2023
  python check_cross_period.py --full            # base inteira (~145 empresas, ~1 min)
"""
import pandas as pd

from consistency_utils import (add_common_args, clear_flags, finish_run, get_db, latest_rows,
                               new_run, parent_code, tolerancia, total_codes, write_flags)

LAYER = 2
CHECK_TYPE = "cross_period"
SEVERITY = {"reapresentacao": "warn", "reclassificacao": "info"}
DOC_COLS = ["data_referencia", "fonte", "ordem_exercicio"]   # ordem = critério de baseline
GROUP_COLS = ["cnpj_companhia", "tipo_doc", "periodo_ini", "periodo_fim"]
RESUMO_KEYS = ["linhas_comuns", "linhas_divergentes", "linhas_exclusivas_ref",
               "linhas_exclusivas_cmp", "total_disponivel"]


def compare_pair(ref: pd.DataFrame, cmp: pd.DataFrame, tipo_doc: str,
                 tol_abs: float = 1000.0, tol_rel: float = 0.005) -> tuple[list[dict], dict]:
    """Compara as linhas de UM período em dois documentos (já filtradas).

    Retorna (flags_de_linha, resumo). As flags vêm só com os campos da linha
    (cd_conta, valores, classificacao, severity); o chamador acrescenta o
    contexto do par (cnpj, período, documentos).
    """
    # merge interno + diferença de conjuntos (indicator=True dispara FutureWarning
    # dentro do pandas 2.2 e não acrescenta nada aqui)
    comuns = ref[["cd_conta", "ds_conta", "vl_conta"]].merge(
        cmp[["cd_conta", "ds_conta", "vl_conta"]], on="cd_conta", how="inner",
        suffixes=("_ref", "_cmp"),
    )
    codigos_ref, codigos_cmp = set(ref["cd_conta"]), set(cmp["cd_conta"])
    v_ref = comuns["vl_conta_ref"].astype(float).fillna(0.0)
    v_cmp = comuns["vl_conta_cmp"].astype(float).fillna(0.0)
    divergentes = comuns[(v_cmp - v_ref).abs() > tolerancia(v_ref, tol_abs, tol_rel)]

    totais = total_codes(tipo_doc, ref)
    total_disponivel = bool(comuns["cd_conta"].isin(totais).any())
    classe = "reapresentacao" if divergentes["cd_conta"].isin(totais).any() else "reclassificacao"

    resumo = {
        "classificacao": classe,
        "linhas_comuns": int(len(comuns)),
        "linhas_divergentes": int(len(divergentes)),
        "linhas_exclusivas_ref": len(codigos_ref - codigos_cmp),
        "linhas_exclusivas_cmp": len(codigos_cmp - codigos_ref),
        "total_disponivel": total_disponivel,
    }
    flags = []
    for r in divergentes.itertuples(index=False):
        ref_v = 0.0 if pd.isna(r.vl_conta_ref) else float(r.vl_conta_ref)
        cmp_v = 0.0 if pd.isna(r.vl_conta_cmp) else float(r.vl_conta_cmp)
        flags.append({
            "cd_conta": r.cd_conta,
            "cd_conta_pai": parent_code(r.cd_conta),
            "ds_conta": r.ds_conta_ref if not pd.isna(r.ds_conta_ref) else r.ds_conta_cmp,
            "valor_ref": ref_v,
            "valor_cmp": cmp_v,
            "diff_abs": cmp_v - ref_v,
            "diff_rel": (cmp_v - ref_v) / abs(ref_v) if ref_v else None,
            "classificacao": classe,
            "severity": SEVERITY[classe],
        })
    return flags, resumo


def _doc_rows(grupo: pd.DataFrame, doc) -> pd.DataFrame:
    mask = ((grupo["data_referencia"] == doc.data_referencia)
            & (grupo["fonte"] == doc.fonte)
            & (grupo["ordem_exercicio"] == doc.ordem_exercicio))
    return grupo[mask]


def check_cross_period(df: pd.DataFrame, tol_abs: float = 1000.0,
                       tol_rel: float = 0.005) -> tuple[list[dict], dict]:
    """df = saída de latest_rows (qualquer escopo). Retorna (flags, stats).

    stats[tipo_doc] = {"pares": n, "pares_divergentes": m, "reapresentacao": k},
    contando pares (documento_ref, documento_cmp, período).
    Linhas com periodo_fim NULL são ignoradas (groupby descarta NaN na chave).
    """
    flags: list[dict] = []
    stats: dict = {}
    if df.empty:
        return flags, stats
    for (cnpj, tipo_doc, p_ini, p_fim), grupo in df.groupby(GROUP_COLS, sort=True):
        docs = list(grupo[DOC_COLS].drop_duplicates().sort_values(DOC_COLS).itertuples(index=False))
        if len(docs) < 2:
            continue
        st = stats.setdefault(tipo_doc, {"pares": 0, "pares_divergentes": 0, "reapresentacao": 0})
        ref_doc = docs[0]
        ref = _doc_rows(grupo, ref_doc)
        for cmp_doc in docs[1:]:
            st["pares"] += 1
            linhas, resumo = compare_pair(ref, _doc_rows(grupo, cmp_doc), tipo_doc, tol_abs, tol_rel)
            if resumo["linhas_divergentes"] == 0:
                continue
            st["pares_divergentes"] += 1
            if resumo["classificacao"] == "reapresentacao":
                st["reapresentacao"] += 1
            contexto = {
                "layer": LAYER, "check_type": CHECK_TYPE,
                "cnpj_companhia": cnpj, "tipo_doc": tipo_doc,
                "periodo_ini": p_ini, "periodo_fim": p_fim,
                "fonte_ref": ref_doc.fonte, "data_ref": ref_doc.data_referencia, "ordem_ref": ref_doc.ordem_exercicio,
                "fonte_cmp": cmp_doc.fonte, "data_cmp": cmp_doc.data_referencia, "ordem_cmp": cmp_doc.ordem_exercicio,
            }
            flags.extend({**contexto, **linha} for linha in linhas)
            flags.append({
                **contexto,
                "cd_conta": None,
                "classificacao": resumo["classificacao"],
                "severity": SEVERITY[resumo["classificacao"]],
                "detalhe": {k: resumo[k] for k in RESUMO_KEYS},
            })
    return flags, stats
