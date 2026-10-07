"""Etapa 4, critérios de pronto no banco real (só leitura): latência da busca por trecho, repetição no top-10
e o teste de item conhecido sobre ipe_chunks de verdade.

    .venv/bin/python docs/proximos-passos/stress/st4_busca_real.py
"""
import os, random, re, sqlite3, statistics, sys, time, unicodedata
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "mcp"))
import cvm_mcp

random.seed(7)
c = sqlite3.connect(f"file:{cvm_mcp.DB_PATH}?mode=ro", uri=True)
STOP = set("para pelo pela como mais sobre entre quando desde dessa desse deste desta ainda sendo foram serão seus suas assim também outros outras nosso nossa acordo companhia empresa conforme relação durante através junto neste nesta".split())
sa = lambda s: unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
n_chunks = c.execute("SELECT MAX(chunk_id) FROM ipe_chunks").fetchone()[0]
df = Counter()
for (t,) in c.execute("SELECT texto FROM ipe_chunks WHERE chunk_id % 200 = 0"):
    df.update(set(re.findall(r"[a-z]{6,}", sa(t))))

lat, dups, hits, chars, feitos = [], 0, [], [], 0
while feitos < 300:
    row = c.execute("SELECT chunk_id, cnpj_companhia, rep_protocolo, texto FROM ipe_chunks WHERE chunk_id = ?",
                    (random.randint(1, n_chunks),)).fetchone()
    if not row:
        continue
    cid, cnpj, proto, txt = row
    termos = [w for w in dict.fromkeys(re.findall(r"[a-z]{6,}", sa(txt))) if w not in STOP]
    termos = sorted(termos, key=lambda w: df.get(w, 0))[2:6]
    if len(termos) < 4:
        continue
    feitos += 1
    t = time.time()
    r = cvm_mcp.search_docs(" ".join(termos), versoes_antigas=True, k=10)   # sem filtro de empresa, como no stress
    lat.append(time.time() - t)
    trechos = [l[6] for l in r["linhas"]]
    dups += len(trechos) - len(set(trechos))
    protos = [l[0] for l in r["linhas"]]
    # o trecho vale em todos os documentos que o contêm (dedup), não só no representante
    donos = {r[0] for r in c.execute("SELECT protocolo_entrega FROM ipe_chunk_docs WHERE chunk_id = ?", (cid,))}
    rk = next((i + 1 for i, p in enumerate(protos) if p in donos), None)
    hits.append(rk)
    if rk:
        chars.append(sum(1 for _ in range(rk)) * 2000)     # trechos lidos até o acerto × ~2 mil

lat.sort()
n = len(hits)
print(f"consultas={n}  hit@1={sum(1 for h in hits if h==1)/n:.1%}  hit@5={sum(1 for h in hits if h and h<=5)/n:.1%}")
print(f"chars lidos até o trecho (p50, estimado a 2 mil por trecho)={statistics.median(chars):,.0f}")
print(f"latência p50={statistics.median(lat)*1000:.0f} ms  p95={lat[int(.95*n)]*1000:.0f} ms  max={lat[-1]*1000:.0f} ms")
print(f"trechos repetidos dentro do top-10: {dups}")
# filtros por empresa e categoria
tl = []
for tk in ("PETR4", "VALE3", "WEGE3", "ITUB4", "LREN3"):
    for q in ("dividendos", "aquisição participação", "remuneração administradores", "recompra ações"):
        t = time.time(); r = cvm_mcp.search_docs(q, ticker=tk, categorias=["Fato Relevante", "Comunicado ao Mercado"]); tl.append(time.time() - t)
tl.sort()
print(f"com ticker+categoria: p50={statistics.median(tl)*1000:.0f} ms p95={tl[int(.95*len(tl))]*1000:.0f} ms")
