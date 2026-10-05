"""Stress test da Etapa 6: persistir a linha econômica (encadeamento por empresa) com o
match_filings que a Camada 6 e o visualizador já usam.

Mede, para DFC (o pior caso) e DRE/BPP: quanto das linhas N casa entre filings, com que
classe, quanto cai em 'ambiguo', quantas linhas econômicas uma empresa acumula no histórico
(explosão de IDs = casamento falhando) e quanto custa rodar a base inteira.

    python st6_linha_economica.py /caminho/cvm_research.db
"""
import sqlite3
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, "scripts/analysis")
from check_text_stability import match_filings  # noqa: E402

c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
plano = {(r[0], r[1], r[2]): r[3] for r in c.execute("SELECT cnpj_companhia, fonte, data_referencia, plano_contas FROM vw_plano_contas")}

def carregar(td):
    rows = c.execute("""
        WITH v AS (SELECT cnpj_companhia, fonte, data_referencia, MAX(versao) versao FROM demonstrativos_contabeis
                   WHERE tipo_doc=? AND ordem_exercicio='Último' GROUP BY 1,2,3)
        SELECT d.cnpj_companhia, d.fonte, d.data_referencia, d.cd_conta, d.ds_conta, d.st_conta_fixa
        FROM demonstrativos_contabeis d JOIN v USING (cnpj_companhia, fonte, data_referencia, versao)
        WHERE d.tipo_doc=? AND d.ordem_exercicio='Último'""", (td, td)).fetchall()
    f = defaultdict(dict)
    for cn, fo, dr, cd, ds, st in rows:
        if plano.get((cn, fo, dr), "padrao") == "padrao":
            f[(cn, fo, dr)][cd] = (ds, st)
    return f

for td in ["DFC_MI", "DRE", "BPP"]:
    t0 = time.time()
    f = carregar(td)
    empresas = sorted({k[0] for k in f})
    stats = {"ITR 3T → DFP": Counter(), "DFP(Y−1) → DFP(Y)": Counter(), "sequência trimestral": Counter()}
    ids_por_empresa = []
    t = time.time()
    for cn in empresas:
        dfp = sorted(dr for (c2, fo, dr) in f if c2 == cn and fo == "DFP")
        itr = {dr for (c2, fo, dr) in f if c2 == cn and fo == "ITR"}
        pares = []
        for dr in dfp:
            t3 = dr[:4] + "-09-30"
            if t3 in itr:
                pares.append(("ITR 3T → DFP", ("ITR", t3), ("DFP", dr)))
        for a, b in zip(dfp, dfp[1:]):
            pares.append(("DFP(Y−1) → DFP(Y)", ("DFP", a), ("DFP", b)))
        for tipo, (fa, da), (fb, db) in pares:
            A, B = f[(cn, fa, da)], f[(cn, fb, db)]
            m = match_filings(A, B)
            for cd, (ds, st) in B.items():
                if st != "N":
                    continue
                stats[tipo][m[cd][1] if cd in m else "sem_par"] += 1
        # sequência completa (ITR e DFP em ordem) → quantas linhas econômicas distintas a empresa acumula
        seq = sorted([(dr, fo) for (c2, fo, dr) in f if c2 == cn], key=lambda x: (x[0], x[1] == "DFP"))
        vivos = {}      # cd no filing atual -> id
        prox = 0
        for i, (dr, fo) in enumerate(seq):
            B = f[(cn, fo, dr)]
            if i:
                m = match_filings(f[(cn, seq[i-1][1], seq[i-1][0])], B)
            else:
                m = {}
            novos = {}
            for cd, (ds, st) in B.items():
                par = m.get(cd)
                if par and par[1] != "ambiguo" and par[0] in vivos:
                    novos[cd] = vivos[par[0]]
                else:
                    novos[cd] = prox; prox += 1
                if st == "N" and i:
                    stats["sequência trimestral"][par[1] if par else "sem_par"] += 1
            vivos = novos
        n_filing_medio = sum(len(f[(cn, fo, dr)]) for dr, fo in seq) / max(len(seq), 1)
        ids_por_empresa.append(prox / max(n_filing_medio, 1))
    print(f"\n== {td}: {len(f)} filings, {len(empresas)} empresas, casamento em {time.time()-t:.0f}s (carga {t - t0:.0f}s)")
    for tipo, cnt in stats.items():
        n = sum(cnt.values())
        print(f"  {tipo:22s} linhas N={n:7d}  " + "  ".join(f"{k}={v/n:.1%}" for k, v in cnt.most_common()))
    ids_por_empresa.sort()
    print(f"  linhas econômicas acumuladas no histórico ÷ linhas de um filing médio: p50={ids_por_empresa[len(ids_por_empresa)//2]:.1f} "
          f"p90={ids_por_empresa[int(.9*len(ids_por_empresa))]:.1f} max={ids_por_empresa[-1]:.1f}")
