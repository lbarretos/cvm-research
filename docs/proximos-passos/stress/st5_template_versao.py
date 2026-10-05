"""Stress test da Etapa 5: detectar a versão do template da CVM de cada filing pela
"impressão digital" das contas fixas (st_conta_fixa='S').

Hipótese a testar: (1) poucas impressões digitais explicam todos os filings; (2) cada empresa
migra uma vez e não volta; (3) a Camada 5 hoje classifica essas trocas como 'estavel'.

    python st5_template_versao.py /caminho/cvm_research.db
"""
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "scripts/analysis")
from consistency_utils import normalize_text  # noqa: E402

c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
plano = {(r[0], r[1], r[2]): r[3] for r in c.execute("SELECT cnpj_companhia, fonte, data_referencia, plano_contas FROM vw_plano_contas")}
rows = c.execute("""
    WITH v AS (SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) versao
               FROM demonstrativos_contabeis WHERE ordem_exercicio='Último' GROUP BY 1,2,3,4)
    SELECT d.cnpj_companhia, d.fonte, d.tipo_doc, d.data_referencia, d.cd_conta, d.ds_conta
    FROM demonstrativos_contabeis d JOIN v USING (cnpj_companhia, fonte, tipo_doc, data_referencia, versao)
    WHERE d.ordem_exercicio='Último' AND d.st_conta_fixa='S'""").fetchall()

fp = defaultdict(dict)
for cn, fo, td, dr, cd, ds in rows:
    fp[(cn, fo, td, dr)][cd] = normalize_text(ds)

# Impressão digital = o dicionário código → nome das contas S. Empresas omitem contas S vazias,
# então duas impressões são da mesma versão se não se contradizem (nenhum código com nome diferente).
# Agrupamento guloso: cada filing entra na primeira versão compatível; conflito abre versão nova.
por_grupo = defaultdict(list)
for k, d in fp.items():
    por_grupo[(plano.get((k[0], k[1], k[3]), "padrao"), k[2])].append((k, d))

resumo = []
atribuicao = {}
for (pl, td), itens in sorted(por_grupo.items()):
    itens.sort(key=lambda x: (x[0][3], x[0][0]))
    versoes = []   # [dict união código→nome, contagem, primeira, última]
    for k, d in itens:
        for i, v in enumerate(versoes):
            if all(v[0].get(cd, nm) == nm for cd, nm in d.items()):
                v[0].update(d); v[1] += 1; v[3] = max(v[3], k[3]); atribuicao[k] = i
                break
        else:
            versoes.append([dict(d), 1, k[3], k[3]]); atribuicao[k] = len(versoes) - 1
    resumo.append((pl, td, [(v[1], v[2], v[3]) for v in versoes]))

print("Versões de template detectadas (filings, primeira data, última data):")
for pl, td, vs in resumo:
    print(f"  {pl:10s} {td:6s} {len(vs)} versões: " + "; ".join(f"v{i}={n} [{a}..{b}]" for i, (n, a, b) in enumerate(vs)))

# (2) monotonicidade: por empresa, fonte e tipo_doc, a versão nunca volta atrás
voltas = Counter(); trocas = Counter(); total = Counter()
seq = defaultdict(list)
for k, v in atribuicao.items():
    seq[(k[0], k[1], k[2])].append((k[3], v))
for (cn, fo, td), s in seq.items():
    s.sort(); vs = [v for _, v in s]
    total[td] += 1
    mud = sum(1 for a, b in zip(vs, vs[1:]) if a != b)
    if mud:
        trocas[td] += 1
    if any(b < a for a, b in zip(vs, vs[1:])):
        voltas[td] += 1
print("\nSéries (empresa×fonte×tipo_doc) com troca de versão / que voltam para versão anterior:")
for td in sorted(total):
    print(f"  {td:6s} séries={total[td]:4d}  com troca={trocas[td]:4d}  voltam atrás={voltas[td]:3d}")

# (3) o que a Camada 5 gravou nas contas S que mudaram de nome no mesmo código
mudaram = set()
for (cn, fo, td), s in seq.items():
    s.sort()
    for (d1, _), (d2, _) in zip(s, s[1:]):
        a, b = fp[(cn, fo, td, d1)], fp[(cn, fo, td, d2)]
        for cd in a.keys() & b.keys():
            if a[cd] != b[cd]:
                mudaram.add((cn, td, fo, d2, cd))
tl = {(r[0], r[1], r[2], r[3], r[4]): r[5] for r in c.execute(
    "SELECT cnpj_companhia, tipo_doc, fonte, data_referencia, cd_conta, classificacao FROM cd_conta_ds_timeline")}
cls = Counter(tl.get(k, "estavel (não gravada)") for k in mudaram)
print(f"\nContas S com mesmo código e nome diferente entre filings consecutivos: {len(mudaram)}")
print("  como a Camada 5 classificou:", dict(cls))

# (4) ambiguidade: filings compatíveis com mais de uma versão (omitem justamente as contas que as distinguem)
print("\nFilings compatíveis com 2+ versões (a atribuição gulosa pode errar nesses):")
voltas_amb = Counter()
for (pl, td), itens in sorted(por_grupo.items()):
    vs = [v for p2, t2, v in resumo if (p2, t2) == (pl, td)][0]
    # reconstrói as uniões finais
    unioes = defaultdict(dict)
    for k, d in itens:
        unioes[atribuicao[k]].update(d)
    amb = sum(1 for k, d in itens
              if sum(all(u.get(cd, nm) == nm for cd, nm in d.items()) for u in unioes.values()) > 1)
    print(f"  {pl:10s} {td:6s} {amb:5d} de {len(itens)}")
