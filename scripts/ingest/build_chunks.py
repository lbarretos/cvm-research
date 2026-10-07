"""
Etapa 4: divide o texto da camada quente do IPE em trechos de ~2 mil caracteres, deduplica por
empresa e indexa no FTS5 (ipe_chunks_fts). A camada fria (DFs completas, prospectos...) continua
só no FTS por documento (ipe_docs_fts).

Camada quente: FR, CM, AVI, RCA, Assembleia (ata, proposta, sumário, edital) e press-release.

Uso (rodar de scripts/ingest, com DATABASE_URL no .env):
  python build_chunks.py              # incremental: só documentos ainda sem trechos
  python build_chunks.py --rebuild    # apaga e refaz tudo (depois de repair_text_encoding, por ex.)
  python build_chunks.py --versoes    # só recalcula ipe_versoes e is_latest dos trechos
  python build_chunks.py --limite 500 # só os 500 primeiros pendentes (teste)

Antes da primeira vez: sqlite3 cvm_research.db < scripts/migrations/2026-10-06_ipe_chunks.sql
"""
import argparse
import hashlib
import re
import time
from collections import Counter

from utils import get_db

QUENTE = """(categoria IN ('Fato Relevante','Comunicado ao Mercado','Aviso aos Acionistas','Reunião da Administração')
  OR (categoria = 'Assembleia' AND especie IN ('Ata','Proposta da Administração','Sumário das Decisões','Edital de Convocação'))
  OR (categoria = 'Dados Econômico-Financeiros' AND tipo = 'Press-release'))"""

ALVO, SOBRA = 2000, 200
_HIFEN = re.compile(r"(\w)-\n(\w)")


def limpar(txt: str) -> str:
    """Junta hifenização de fim de linha, tira cabeçalho/rodapé (linha curta que repete 3+ vezes) e colapsa espaços."""
    txt = _HIFEN.sub(r"\1\2", txt)
    linhas = txt.split("\n")
    freq = Counter(l.strip() for l in linhas if 0 < len(l.strip()) <= 80)
    rep = {l for l, n in freq.items() if n >= 3 and not re.fullmatch(r"[\d\W]*", l)}
    txt = re.sub(r"[ \t]+", " ", "\n".join(l for l in linhas if l.strip() not in rep))
    return re.sub(r"\n{3,}", "\n\n", txt)


def dividir(txt: str, alvo: int = ALVO, sobra: int = SOBRA) -> list[str]:
    """Trechos de ~alvo caracteres, cortados em parágrafo, com `sobra` caracteres de sobreposição."""
    pars = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.;:])\n", txt) if p.strip()]
    out, cur = [], ""
    for p in pars:
        while len(p) > alvo * 1.5:               # parágrafo gigante (tabela): corte duro
            out.append((cur + "\n" + p[:alvo]).strip())
            cur, p = "", p[alvo - sobra:]
        if len(cur) + len(p) > alvo and cur:
            out.append(cur.strip())
            cur = cur[-sobra:]
        cur += "\n" + p
    if cur.strip():
        out.append(cur.strip())
    return out


def hash_trecho(t: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", "", t.lower()).encode()).hexdigest()[:20]


def atualizar_versoes(conn) -> int:
    """ipe_versoes para TODOS os documentos; depois propaga is_latest aos trechos (só o que mudou)."""
    conn.execute("DELETE FROM ipe_versoes")
    conn.execute("""
        INSERT INTO ipe_versoes (protocolo_entrega, is_latest, substituido_por)
        SELECT protocolo_entrega,
               CASE WHEN rn = 1 THEN 1 ELSE 0 END,
               CASE WHEN rn = 1 THEN NULL ELSE vigente END
        FROM (
          SELECT protocolo_entrega,
                 ROW_NUMBER() OVER w AS rn,
                 FIRST_VALUE(protocolo_entrega) OVER w AS vigente
          FROM ipe_docs
          WINDOW w AS (PARTITION BY cnpj_companhia, COALESCE(categoria,''), COALESCE(tipo,''),
                                    COALESCE(especie,''), COALESCE(data_referencia,''), COALESCE(assunto,'')
                       ORDER BY data_entrega DESC, protocolo_entrega DESC)
        )""")
    conn.execute("""
        CREATE TEMP TABLE novo_latest AS
        SELECT d.chunk_id, MAX(v.is_latest) AS l
        FROM ipe_chunk_docs d JOIN ipe_versoes v USING (protocolo_entrega)
        GROUP BY d.chunk_id""")
    cur = conn.execute("""
        UPDATE ipe_chunks SET is_latest = (SELECT l FROM novo_latest n WHERE n.chunk_id = ipe_chunks.chunk_id)
        WHERE chunk_id IN (SELECT chunk_id FROM novo_latest)
          AND is_latest <> (SELECT l FROM novo_latest n WHERE n.chunk_id = ipe_chunks.chunk_id)""")
    conn.execute("DROP TABLE novo_latest")
    conn.commit()
    return cur.rowcount


def indexar_documento(conn, d: dict, texto: str) -> tuple[int, int]:
    """Grava os trechos de um documento. Devolve (trechos novos, trechos que já existiam)."""
    novos = repetidos = 0
    cnpj_tok = re.sub(r"\D", "", d["cnpj_companhia"])
    for ordem, t in enumerate(dividir(limpar(texto))):
        h = hash_trecho(t)
        row = conn.execute("SELECT chunk_id, data_entrega FROM ipe_chunks WHERE cnpj_companhia=? AND hash=?",
                           (d["cnpj_companhia"], h)).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO ipe_chunks (cnpj_companhia, cnpj_tok, hash, texto, rep_protocolo, rep_ordem, categoria, tipo,"
                " especie, assunto, data_entrega) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (d["cnpj_companhia"], cnpj_tok, h, t, d["protocolo_entrega"], ordem, d["categoria"], d["tipo"],
                 d["especie"], d["assunto"], d["data_entrega"]))
            cid = cur.lastrowid
            conn.execute("INSERT INTO ipe_chunks_fts (rowid, texto, cnpj_tok) VALUES (?,?,?)", (cid, t, cnpj_tok))
            novos += 1
        else:
            cid = row[0]
            repetidos += 1
            if (d["data_entrega"] or "") > (row[1] or ""):   # o representante é o documento mais recente
                conn.execute("UPDATE ipe_chunks SET rep_protocolo=?, rep_ordem=?, categoria=?, tipo=?, especie=?,"
                             " assunto=?, data_entrega=? WHERE chunk_id=?",
                             (d["protocolo_entrega"], ordem, d["categoria"], d["tipo"], d["especie"],
                              d["assunto"], d["data_entrega"], cid))
        conn.execute("INSERT OR REPLACE INTO ipe_chunk_docs (chunk_id, protocolo_entrega, ordem) VALUES (?,?,?)",
                     (cid, d["protocolo_entrega"], ordem))
    return novos, repetidos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--versoes", action="store_true")
    ap.add_argument("--limite", type=int)
    a = ap.parse_args()

    conn = get_db()
    conn.row_factory = None
    t0 = time.time()
    if a.rebuild:
        conn.executescript("DELETE FROM ipe_chunk_docs; DELETE FROM ipe_chunks; "
                           "INSERT INTO ipe_chunks_fts(ipe_chunks_fts) VALUES ('delete-all');")
    if not a.versoes:
        sql = f"""SELECT protocolo_entrega, cnpj_companhia, categoria, tipo, especie, assunto, data_entrega
                  FROM ipe_docs WHERE texto_extraido IS NOT NULL AND length(texto_extraido) > 0 AND {QUENTE}
                    AND protocolo_entrega NOT IN (SELECT DISTINCT protocolo_entrega FROM ipe_chunk_docs)
                  ORDER BY data_entrega"""
        if a.limite:
            sql += f" LIMIT {int(a.limite)}"
        docs = conn.execute(sql).fetchall()
        cols = ["protocolo_entrega", "cnpj_companhia", "categoria", "tipo", "especie", "assunto", "data_entrega"]
        print(f"{len(docs)} documentos pendentes")
        novos = rep = 0
        for i, row in enumerate(docs, 1):
            d = dict(zip(cols, row))
            (txt,) = conn.execute("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega=?",
                                  (d["protocolo_entrega"],)).fetchone()
            n, r = indexar_documento(conn, d, txt)
            novos += n
            rep += r
            if i % 500 == 0:
                conn.commit()
                print(f"  {i}/{len(docs)}  trechos novos={novos} repetidos={rep}  ({time.time()-t0:.0f}s)", flush=True)
        conn.commit()
        print(f"trechos novos={novos}, repetidos (deduplicados)={rep}")
    mudou = atualizar_versoes(conn)
    print(f"versões atualizadas; {mudou} trechos mudaram de is_latest ({time.time()-t0:.0f}s)")
    if a.rebuild or not a.versoes:
        conn.execute("INSERT INTO ipe_chunks_fts(ipe_chunks_fts) VALUES ('optimize')")
        conn.commit()


if __name__ == "__main__":
    main()
