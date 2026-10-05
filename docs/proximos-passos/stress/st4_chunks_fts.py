"""Stress test da Etapa 4: limpeza + chunks + FTS por trecho, contra o FTS por documento de hoje.

Copia uma amostra da camada "quente" (FR, CM, AVI, Assembleia, RCA e press-release de um ano)
para um banco de rascunho e roda um teste de recuperação de item conhecido (known-item):
sorteia uma frase de um documento, monta a consulta com 4 termos dela e mede se o documento
volta no topo e quantos caracteres o LLM teria que ler para chegar ao trecho.

    python st4_chunks_fts.py /caminho/cvm_research.db /caminho/rascunho.db [ano]
"""
import random
import re
import sqlite3
import statistics
import sys
import time
import unicodedata
from collections import Counter

src, dst = sys.argv[1], sys.argv[2]
ANO = sys.argv[3] if len(sys.argv) > 3 else "2025"
random.seed(42)

QUENTE = """(categoria IN ('Fato Relevante','Comunicado ao Mercado','Aviso aos Acionistas','Reunião da Administração')
  OR (categoria = 'Assembleia' AND especie IN ('Ata','Proposta da Administração','Sumário das Decisões','Edital de Convocação'))
  OR (categoria = 'Dados Econômico-Financeiros' AND tipo = 'Press-release'))"""

c = sqlite3.connect(f"file:{dst}", uri=True)
c.executescript("PRAGMA journal_mode=off; PRAGMA synchronous=off;")
c.execute(f"ATTACH DATABASE 'file:{src}?mode=ro' AS src")
c.executescript("DROP TABLE IF EXISTS docs; DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS docs_fts; DROP TABLE IF EXISTS chunks_fts;")
t = time.time()
c.execute(f"""CREATE TABLE docs AS SELECT rowid AS id, protocolo_entrega, cnpj_companhia, categoria, tipo, especie,
    assunto, data_entrega, texto_extraido FROM src.ipe_docs
    WHERE texto_extraido IS NOT NULL AND substr(data_entrega,1,4) = '{ANO}' AND {QUENTE}""")
c.commit()
c.execute("DETACH src")
n_docs, n_chars = c.execute("SELECT COUNT(*), SUM(length(texto_extraido)) FROM docs").fetchone()
print(f"amostra: {n_docs} docs, {n_chars/1e6:.0f} mi chars ({time.time()-t:.0f}s)")

# ── limpeza ──────────────────────────────────────────────────────────────────
HIFEN = re.compile(r"(\w)-\n(\w)")
def limpar(txt):
    antes = len(HIFEN.findall(txt))
    txt = HIFEN.sub(r"\1\2", txt)
    linhas = txt.split("\n")
    # cabeçalho/rodapé: linha curta idêntica que se repete 3+ vezes no documento
    freq = Counter(l.strip() for l in linhas if 0 < len(l.strip()) <= 80)
    rep = {l for l, n in freq.items() if n >= 3 and not re.fullmatch(r"[\d\W]*", l)}
    linhas = [l for l in linhas if l.strip() not in rep]
    txt = re.sub(r"[ \t]+", " ", "\n".join(linhas))
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt, antes, len(rep)

def chunks(txt, alvo=2000, sobra=200):
    pars = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.;:])\n", txt) if p.strip()]
    out, cur = [], ""
    for p in pars:
        while len(p) > alvo * 1.5:                 # parágrafo gigante (tabela): corta duro
            out.append((cur + "\n" + p[:alvo]).strip()); cur = ""; p = p[alvo - sobra:]
        if len(cur) + len(p) > alvo and cur:
            out.append(cur.strip()); cur = cur[-sobra:]
        cur += "\n" + p
    if cur.strip():
        out.append(cur.strip())
    return out

t = time.time()
c.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, doc_id INT, ordem INT, texto TEXT)")
hif_tot = rep_tot = 0
hashes = Counter()
rows = []
for did, txt in c.execute("SELECT id, texto_extraido FROM docs").fetchall():
    limpo, h, r = limpar(txt)
    hif_tot += h; rep_tot += r
    for i, ch in enumerate(chunks(limpo)):
        rows.append((did, i, ch))
        hashes[hash(re.sub(r"\W+", "", ch.lower()))] += 1
c.executemany("INSERT INTO chunks (doc_id, ordem, texto) VALUES (?,?,?)", rows)
n_chunks = len(rows)
dup = sum(n - 1 for n in hashes.values() if n > 1)
lens = sorted(len(r[2]) for r in rows)
print(f"limpeza+chunks: {time.time()-t:.0f}s; hifenizações juntadas={hif_tot}; linhas de cabeçalho/rodapé distintas removidas={rep_tot}")
print(f"chunks: {n_chunks} ({n_chunks/n_docs:.1f}/doc); tamanho p50={lens[len(lens)//2]} p95={lens[int(.95*len(lens))]} max={lens[-1]}; "
      f"chunks duplicados exatos={dup} ({dup/n_chunks:.1%})")

t = time.time()
c.executescript("""
CREATE VIRTUAL TABLE docs_fts USING fts5(texto_extraido, content='docs', content_rowid='id');
INSERT INTO docs_fts(docs_fts) VALUES ('rebuild');
CREATE VIRTUAL TABLE chunks_fts USING fts5(texto, content='chunks', content_rowid='id');
INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild');
""")
c.commit()
print(f"FTS: {time.time()-t:.0f}s")

# ── known-item ───────────────────────────────────────────────────────────────
STOP = set("""para pelo pela pelos pelas como mais sobre entre quando desde dessa desse deste desta ainda sendo
foram serão sera será seus suas assim também tambem outros outras nosso nossa acordo companhia empresa conforme
relação relacao durante através atraves junto neste nesta""".split())
def sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

df = Counter()   # frequência de documento aproximada, para escolher termos distintivos
for (txt,) in c.execute("SELECT texto FROM chunks WHERE id % 20 = 0"):
    df.update(set(re.findall(r"[a-z]{6,}", sem_acento(txt))))

amostra = random.sample(range(1, n_chunks + 1), 400)
res = {"doc": [], "chunk": []}
for cid in amostra:
    did, txt = c.execute("SELECT doc_id, texto FROM chunks WHERE id=?", (cid,)).fetchone()
    termos = [w for w in dict.fromkeys(re.findall(r"[a-z]{6,}", sem_acento(txt))) if w not in STOP]
    termos = sorted(termos, key=lambda w: df.get(w, 0))[2:6]   # raros, mas não o mais raro (evita erro de OCR)
    if len(termos) < 4:
        continue
    q = " AND ".join(termos)
    t = time.time()
    top_d = [r[0] for r in c.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT 10", (q,))]
    td = time.time() - t
    t = time.time()
    top_c = c.execute("SELECT c.doc_id, length(c.texto) FROM chunks_fts f JOIN chunks c ON c.id=f.rowid "
                      "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 10", (q,)).fetchall()
    tc = time.time() - t
    doclen = c.execute("SELECT length(texto_extraido) FROM docs WHERE id=?", (did,)).fetchone()[0]
    rk_d = top_d.index(did) + 1 if did in top_d else None
    ids_c = [r[0] for r in top_c]
    rk_c = ids_c.index(did) + 1 if did in ids_c else None
    # chars para chegar ao trecho: doc inteiro (hoje, sem saber onde está) × soma dos chunks até o acerto
    res["doc"].append((rk_d, doclen, td))
    res["chunk"].append((rk_c, sum(l for _, l in top_c[:rk_c]) if rk_c else None, tc))

for k, v in res.items():
    n = len(v)
    h1 = sum(1 for r in v if r[0] == 1) / n
    h5 = sum(1 for r in v if r[0] and r[0] <= 5) / n
    chars = [r[1] for r in v if r[0]]
    lat = sorted(r[2] for r in v)
    print(f"{k:6s} n={n} hit@1={h1:.1%} hit@5={h5:.1%}  chars lidos até o trecho p50={statistics.median(chars):,.0f} "
          f"p90={sorted(chars)[int(.9*len(chars))]:,.0f}  latência p50={statistics.median(lat)*1000:.1f} ms p95={lat[int(.95*n)]*1000:.1f} ms")

# ── hifenização: palavras que só existem inteiras depois da limpeza ─────────
achados = Counter()
for (txt,) in c.execute("SELECT texto_extraido FROM docs WHERE id % 7 = 0"):
    for a, b in re.findall(r"([A-Za-zÀ-ú]{3,})-\n([a-zà-ú]{3,})", txt):
        achados[sem_acento(a + b)] += 1
ok = perdidos = 0
for w, _ in achados.most_common(60):
    nd = c.execute("SELECT COUNT(*) FROM docs_fts WHERE docs_fts MATCH ?", (w,)).fetchone()[0]
    nc = c.execute("SELECT COUNT(DISTINCT c.doc_id) FROM chunks_fts f JOIN chunks c ON c.id=f.rowid WHERE chunks_fts MATCH ?", (w,)).fetchone()[0]
    ok += nc; perdidos += max(nc - nd, 0)
print(f"hifenização: nas 60 palavras mais quebradas, a busca por documento acha {ok - perdidos} docs e a por trecho limpo acha {ok} "
      f"(+{perdidos}, {perdidos/max(ok - perdidos, 1):.1%} a mais)")
print("tamanho em disco do rascunho:", c.execute("SELECT page_count*page_size/1e6 FROM pragma_page_count(), pragma_page_size()").fetchone()[0], "MB")

# ── de onde vêm os chunks duplicados ────────────────────────────────────────
grupos = {}
for cid, did, cn, txt in c.execute("SELECT c.id, c.doc_id, d.cnpj_companhia, c.texto FROM chunks c JOIN docs d ON d.id=c.doc_id"):
    grupos.setdefault(hash(re.sub(r"\W+", "", txt.lower())), []).append((did, cn))
tipos = Counter()
for g in grupos.values():
    if len(g) < 2:
        continue
    docs_g = {d for d, _ in g}; emp = {e for _, e in g}
    extra = len(g) - 1
    if len(docs_g) == 1:
        tipos["mesmo documento"] += extra
    elif len(emp) == 1:
        tipos["outro documento da mesma empresa"] += extra
    else:
        tipos["empresas diferentes (boilerplate)"] += extra
print("chunks duplicados por origem:", dict(tipos))
