"""Etapa 6: fragmentação das linhas econômicas (só linhas N), com e sem reatar pelo (pai, nome).

fragmentação = linhas econômicas acumuladas no histórico ÷ linhas N de um filing médio (1,0 = série perfeita).

    cd scripts/analysis && ../../.venv/bin/python ../../docs/proximos-passos/stress/st6_fragmentacao.py
"""
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, ".")
import linha_economica as le  # noqa: E402
from check_text_stability import _linhas  # noqa: E402
from consistency_utils import get_db, latest_rows  # noqa: E402

conn = get_db()
cnpjs = [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
res = {(t, v): [] for t in ("DRE", "BPP", "DFC_MI") for v in (False, True)}
for c in cnpjs:
    df = latest_rows(conn, cnpj=c)
    df = df[df["ordem_exercicio"] == "Último"]
    for tipo, g in df.groupby("tipo_doc"):
        if tipo not in ("DRE", "BPP", "DFC_MI"):
            continue
        filings = sorted({(d, f) for d, f in zip(g["data_referencia"], g["fonte"])})
        cols = [_linhas(g[(g["data_referencia"] == d) & (g["fonte"] == f)]) for d, f in filings]
        n_medio = statistics.mean(sum(1 for _ds, st in col.values() if st == "N") for col in cols)
        if not n_medio:
            continue
        for reatar in (False, True):
            series = le.encadear(cols, reatar_por_pai=reatar)
            n_series = sum(1 for s in series if any(cols[i][cd][1] == "N" for i, cd in s.items()))
            res[(tipo, reatar)].append(n_series / n_medio)

print(f"{'tipo':8s}{'reatar_por_pai':>16s}{'p50':>7s}{'p90':>7s}{'max':>7s}")
for (tipo, reatar), v in res.items():
    v.sort()
    print(f"{tipo:8s}{str(reatar):>16s}{statistics.median(v):7.1f}{v[int(.9 * len(v))]:7.1f}{v[-1]:7.1f}")
