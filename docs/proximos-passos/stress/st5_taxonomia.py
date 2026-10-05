"""Stress test da Etapa 5: conceitos canônicos da DFC por regras + modelo supervisionado.

Testes: (a) cobertura; (b) dupla contagem (linha em 2 conceitos); (c) sinal esperado;
(d) conceito maior que o pai; (e) gabarito externo D&A × DVA 7.04.01 com diagnóstico das falhas;
(f) generalização para empresas nunca vistas (GroupKFold por empresa) e o que o modelo acha
que as regras perderam; (g) quebras de série (conceito some e volta).

Requer scikit-learn (não está na .venv do projeto):
    python -m venv /tmp/v && /tmp/v/bin/pip install -r requirements.txt scikit-learn
    /tmp/v/bin/python st5_taxonomia.py /caminho/cvm_research.db
Rodar da raiz do projeto (importa scripts/analysis/consistency_utils).
"""
import re
import sqlite3
import sys
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/analysis")
from consistency_utils import normalize_text  # noqa: E402

c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
d = pd.read_sql("""
    WITH v AS (SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) versao FROM demonstrativos_contabeis
               WHERE fonte='DFP' AND tipo_doc IN ('DFC_MI','DVA') AND ordem_exercicio='Último' GROUP BY 1,2,3,4)
    SELECT d.cnpj_companhia cnpj, d.tipo_doc, d.data_referencia dref, d.cd_conta cd, d.ds_conta ds, d.vl_conta vl, d.st_conta_fixa st
    FROM demonstrativos_contabeis d JOIN v USING (cnpj_companhia, fonte, tipo_doc, data_referencia, versao)
    WHERE d.ordem_exercicio='Último'""", c)
pl = pd.read_sql("SELECT cnpj_companhia cnpj, data_referencia dref, plano_contas FROM vw_plano_contas WHERE fonte='DFP'", c)
d = d.merge(pl, on=["cnpj", "dref"], how="left")
d = d[d.plano_contas.fillna("padrao") == "padrao"].copy()
d["dsn"] = d.ds.map(normalize_text)
dfc = d[(d.tipo_doc == "DFC_MI")].copy()
dfc["pai"] = dfc.cd.str.rsplit(".", n=1).str[0]
N = dfc[dfc.st == "N"].copy()
nf = dfc[["cnpj", "dref"]].drop_duplicates().shape[0]

# conceito: (prefixo do código, padrão, exclusão, sinal esperado: +1 entrada/adição, -1 saída)
C = {
    "da":              ("6.01.01", r"\b(deprec|amortiz|exaust)", r"(emprest|financ|debent|juros|agio|mais valia|custo de transac|direito de uso|arrend)", +1),
    "da_direito_uso":  ("6.01.01", r"(deprec|amortiz).*(direito de uso|arrend)", None, +1),
    "capex_imob":      ("6.02", r"(aquisic|adic|compra|investimento|aplica).*(imobiliz|ativo fixo|bens do ativo)|^imobilizado$", r"(venda|alienac|recebim|baixa)", -1),
    "capex_intang":    ("6.02", r"(aquisic|adic|compra|investimento|aplica).*intang|^intangivel$", r"(venda|alienac|recebim|imobiliz)", -1),
    "dividendos_pagos":("6.03", r"(dividend|juros sobre (o )?capital|jcp)", r"(recebid|receb)", -1),
    "juros_pagos":     ("6.0", r"(juros|encargos).*(pag|liquid)|pagamento.*(juros|encargos)", r"(capital proprio|sobre (o )?capital|recebid|arrend|direito de uso)", -1),
    "capt_divida":     ("6.03", r"(captac|obtenc|ingresso|emissao|recebimento|novos|contratac).*(emprest|financ|debent|nota|bond)", None, +1),
    "amort_divida":    ("6.03", r"(amortiz|pagamento|liquidac|quitac).*(emprest|financ|debent|nota|bond)", r"(juros|encargos|arrend|direito de uso)", -1),
    "arrend_pago":     ("6.03", r"(arrend|direito de uso|lease|locac)", None, -1),
    "recompra":        ("6.03", r"(recompra|aquisicao de acoes|acoes em tesouraria)", r"(venda|alienac)", -1),
    "ir_pago":         ("6.01", r"(imposto de renda|ir e cs|irpj|contribuicao social).*(pag|recolh)|(pag|recolh).*(imposto de renda|ir e cs|irpj|contribuicao social|tributos sobre o lucro)", None, -1),
}
lab = pd.DataFrame(index=N.index)
for k, (pref, pat, exc, _s) in C.items():
    m = N.cd.str.startswith(pref) & N.dsn.str.contains(pat, regex=True)
    if exc:
        m &= ~N.dsn.str.contains(exc, regex=True)
    lab[k] = m
N["n_conceitos"] = lab.sum(axis=1)
N["conceito"] = np.where(N.n_conceitos == 1, lab.idxmax(axis=1), np.where(N.n_conceitos > 1, "CONFLITO", "outro"))

print(f"DFPs (plano padrão) com DFC: {nf}; linhas N da DFC: {len(N)}")
print("\n(a–c) por conceito: cobertura, dupla contagem e sinal")
for k, (_p, _pat, _e, sinal) in C.items():
    x = N[lab[k]]
    per = x.groupby(["cnpj", "dref"]).size()
    sinal_ok = (np.sign(x.vl.fillna(0)) == sinal) | (x.vl.fillna(0) == 0)
    print(f"  {k:17s} cobertura={len(per)/nf:6.1%}  linhas={len(x):6d}  em 2+ conceitos={int((N.loc[x.index,'n_conceitos']>1).sum()):4d}  "
          f"sinal trocado={1-sinal_ok.mean():5.1%}")
conf = N[N.conceito == "CONFLITO"]
print(f"\n  linhas em conflito (2+ conceitos): {len(conf)}; pares mais comuns:")
print("   ", Counter(tuple(sorted(lab.columns[lab.loc[i]])) for i in conf.index).most_common(5))

# (d) capex maior que o total de saídas de 6.02 (dupla contagem ou linha de outro pai)
cap = N[N.conceito.isin(["capex_imob", "capex_intang"])].groupby(["cnpj", "dref"]).vl.sum()
saidas602 = dfc[(dfc.pai == "6.02") & (dfc.vl < 0)].groupby(["cnpj", "dref"]).vl.sum()
z = pd.concat([cap.rename("capex"), saidas602.rename("saidas")], axis=1).dropna()
print(f"\n(d) capex > soma das saídas de investimento: {(z.capex < z.saidas - 1e3).mean():.2%} dos filings")

# (e) gabarito D&A: DFC × DVA 7.04.01, e diagnóstico das falhas
da = N[N.conceito.isin(["da", "da_direito_uso"])].groupby(["cnpj", "dref"]).vl.sum()
dva = d[(d.tipo_doc == "DVA") & (d.cd == "7.04.01")].groupby(["cnpj", "dref"]).vl.sum().abs()
v = pd.concat([da.rename("dfc"), dva.rename("dva")], axis=1)
v = v[v.dva > 0]
v["dfc"] = v.dfc.fillna(0)
v["r"] = v.dfc / v.dva
ok2 = (v.r - 1).abs() < 0.02
print(f"\n(e) D&A DFC × DVA 7.04.01: n={len(v)}  |r−1|<2%: {ok2.mean():.1%}  <10%: {((v.r-1).abs()<.1).mean():.1%}")
falha = v[~ok2]
cat = pd.cut(falha.r, [-np.inf, 0.001, 0.9, 0.98, 1.02, 1.1, np.inf],
             labels=["DFC sem D&A", "DFC < 90% da DVA", "DFC 90–98%", "—", "DFC 102–110%", "DFC > 110%"])
print("   falhas por faixa:", cat.value_counts().to_dict())
# o que existe em 6.01.01 nos filings em que a DFC ficou abaixo — candidatos que as regras perderam
baixo = falha[falha.r < 0.9].index
cand = N[N.set_index(["cnpj", "dref"]).index.isin(baixo) & N.cd.str.startswith("6.01.01") & (N.conceito == "outro")]
cand = cand[cand.dsn.str.contains(r"deprec|amortiz|exaust|baixa", regex=True)]
print("   linhas com deprec/amortiz/baixa NÃO usadas nos filings abaixo de 90% (top 8):")
for nome, n in cand.dsn.value_counts().head(8).items():
    print(f"     {n:3d}  {nome}")

# (f) generalização para empresas nunca vistas
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.model_selection import GroupKFold
    from scipy.sparse import hstack
    base = N[N.conceito != "CONFLITO"].copy()
    base["txt"] = base.dsn
    base["ctx"] = "pai_" + base.pai.str.replace(".", "_") + " sinal_" + np.sign(base.vl.fillna(0)).astype(int).astype(str)
    v1 = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True)
    v2 = TfidfVectorizer(token_pattern=r"\S+")
    X = hstack([v1.fit_transform(base.txt), v2.fit_transform(base.ctx)]).tocsr()
    y = base.conceito.values
    grupos = base.cnpj.values
    pred = np.empty(len(y), dtype=object)
    proba = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=5).split(X, y, grupos):
        m = LogisticRegression(max_iter=2000, C=4, class_weight="balanced").fit(X[tr], y[tr])
        pred[te] = m.predict(X[te]); proba[te] = m.predict_proba(X[te]).max(axis=1)
    rotulos = [k for k in C]
    print(f"\n(f) modelo (TF-IDF char 3–5 + pai + sinal, regressão logística), validação por empresa nunca vista (GroupKFold=5):")
    print(f"   F1 macro vs regras (nos {len(rotulos)} conceitos): {f1_score(y, pred, labels=rotulos, average='macro'):.3f}; "
          f"concordância geral: {(pred == y).mean():.1%}")
    base["pred"] = pred; base["proba"] = proba
    dis = base[(base.pred != base.conceito)]
    print(f"   discordâncias: {len(dis)} linhas ({len(dis)/len(base):.1%}); com confiança ≥ 0,9: {(dis.proba >= .9).sum()}")
    print("   amostra — modelo diz conceito, regra disse 'outro' (candidatos a regra faltante):")
    for _, r in dis[(dis.conceito == "outro") & (dis.proba >= .9)].drop_duplicates("dsn").sort_values("proba", ascending=False).head(12).iterrows():
        print(f"     {r.proba:.2f} {r.pred:17s} [{r.cd}] {r.dsn[:80]}")
    print("   amostra — regra diz conceito, modelo discorda com confiança (candidatos a falso positivo da regra):")
    for _, r in dis[(dis.conceito != "outro") & (dis.proba >= .8)].drop_duplicates("dsn").sort_values("proba", ascending=False).head(12).iterrows():
        print(f"     {r.proba:.2f} regra={r.conceito:15s} modelo={r.pred:15s} [{r.cd}] {r.dsn[:70]}")
except ImportError:
    print("\n(f) pulado: scikit-learn não instalado")

# (g) quebras de série: conceito presente em Y−1 e Y+1 mas ausente em Y
pres = N[N.conceito.isin(list(C))].groupby(["cnpj", "conceito"]).dref.apply(lambda s: set(s.str[:4]))
anos = dfc.groupby("cnpj").dref.apply(lambda s: sorted(set(s.str[:4])))
buracos = total = 0
for (cn, k), ys in pres.items():
    a = anos[cn]
    for y0, y1, y2 in zip(a, a[1:], a[2:]):
        if y0 in ys and y2 in ys:
            total += 1
            buracos += y1 not in ys
print(f"\n(g) conceito presente em Y−1 e Y+1 mas ausente em Y: {buracos} de {total} ({buracos/max(total,1):.1%})")
