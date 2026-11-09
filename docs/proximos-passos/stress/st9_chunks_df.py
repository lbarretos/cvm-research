"""
Stress test da Etapa 9, Bloco C (item 9.9, 9.10, 9.11):
Monta a camada 'df' (DFP e ITR 2024-2026) num banco temporário para medir:
1. Taxa de deduplicação entre trimestres por empresa (hash).
2. Projeção de GB a mais no banco (teto do critério de pronto: +3 GB).
3. % de trechos com seção / nota detectada (meta: >= 85%).
4. Hit@5 de busca em itens conhecidos (conciliação do IR, subvenções, etc.).

Uso:
    .venv/bin/python docs/proximos-passos/stress/st9_chunks_df.py [caminho/cvm_research.db] [caminho/temp.db]
"""
import hashlib
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

# Adiciona scripts ao path
RAIZ = Path(__file__).resolve().parents[3]
if str(RAIZ / "scripts" / "ingest") not in sys.path:
    sys.path.insert(0, str(RAIZ / "scripts" / "ingest"))

from secoes_notas import (
    extrair_secoes_documento,
    encontrar_secao_do_offset,
    obter_secao_por_chave,
    CANONICAS,
)

ALVO, SOBRA = 2000, 200
_HIFEN = re.compile(r"(\w)-\n(\w)")

DF_TIPOS = (
    "Demonstrações Financeiras Anuais Completas",
    "Demonstrações Financeiras Intermediárias",
    "Demonstrações Financeiras em Padrões Internacionais",
    "Demonstrações Financeiras Adicionais",
)


def limpar(txt: str) -> str:
    """Junta hifenização e remove linhas de cabeçalho repetidas."""
    txt = _HIFEN.sub(r"\1\2", txt)
    linhas = txt.split("\n")
    freq = Counter(l.strip() for l in linhas if 0 < len(l.strip()) <= 80)
    rep = {l for l, n in freq.items() if n >= 3 and not re.fullmatch(r"[\d\W]*", l)}
    txt = re.sub(r"[ \t]+", " ", "\n".join(l for l in linhas if l.strip() not in rep))
    return re.sub(r"\n{3,}", "\n\n", txt)


def dividir_com_offsets(txt: str, alvo: int = ALVO, sobra: int = SOBRA) -> list[tuple[str, int]]:
    """Gera trechos de ~alvo caracteres com sobra, retornando (trecho, offset_inicio_no_texto)."""
    pars = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.;:])\n", txt) if p.strip()]
    out = []
    cur = ""
    cur_pos = 0
    pos_map: list[tuple[str, int]] = []
    
    # Mapeamento aproximado de posições
    scan_pos = 0
    for p in pars:
        p_idx = txt.find(p[:50], scan_pos)
        if p_idx < 0:
            p_idx = scan_pos
        pos_map.append((p, p_idx))
        scan_pos = p_idx + len(p)

    cur = ""
    start_pos = 0
    for p, p_idx in pos_map:
        if not cur:
            start_pos = p_idx
        while len(p) > alvo * 1.5:
            pedaco = p[:alvo]
            out.append(((cur + "\n" + pedaco).strip(), start_pos))
            cur = ""
            p = p[alvo - sobra:]
            start_pos = p_idx + alvo - sobra
        if len(cur) + len(p) > alvo and cur:
            out.append((cur.strip(), start_pos))
            cur = cur[-sobra:]
            start_pos = max(0, p_idx - sobra)
        cur += "\n" + p

    if cur.strip():
        out.append((cur.strip(), start_pos))
    return out


def hash_trecho(t: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", "", t.lower()).encode()).hexdigest()[:20]


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else str(RAIZ / "cvm_research.db")
    dst_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/cvm_stress_st9_chunks.db"

    print(f"=== Stress Test Etapa 9 Bloco C: Camada DF em Chunks ===")
    print(f"Banco fonte: {src_path}")
    print(f"Banco teste: {dst_path}")

    if os.path.exists(dst_path):
        os.remove(dst_path)

    conn_src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    conn_dst = sqlite3.connect(dst_path)
    conn_dst.executescript("PRAGMA journal_mode=off; PRAGMA synchronous=off;")

    conn_dst.executescript("""
        CREATE TABLE chunks (
            chunk_id INTEGER PRIMARY KEY,
            cnpj_companhia TEXT NOT NULL,
            cnpj_tok TEXT NOT NULL,
            hash TEXT NOT NULL,
            texto TEXT NOT NULL,
            rep_protocolo TEXT NOT NULL,
            rep_ordem INTEGER NOT NULL,
            categoria TEXT,
            tipo TEXT,
            data_referencia TEXT,
            data_entrega TEXT,
            secao_num TEXT,
            secao_titulo TEXT,
            secao_canonica TEXT,
            pagina INTEGER,
            UNIQUE(cnpj_companhia, hash)
        );
        CREATE TABLE chunk_docs (
            chunk_id INTEGER NOT NULL,
            protocolo_entrega TEXT NOT NULL,
            ordem INTEGER NOT NULL,
            PRIMARY KEY (protocolo_entrega, ordem)
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            texto,
            cnpj_tok,
            secao_canonica UNINDEXED,
            content='chunks',
            content_rowid='chunk_id'
        );
    """)

    # Carrega DFs de 2024 a 2026
    sql = f"""
        SELECT protocolo_entrega, cnpj_companhia, categoria, tipo, assunto,
               data_referencia, data_entrega, texto_extraido
        FROM ipe_docs
        WHERE tipo IN ({','.join('?' * len(DF_TIPOS))})
          AND data_referencia >= '2024-01-01'
          AND texto_extraido IS NOT NULL
        ORDER BY data_referencia ASC, data_entrega ASC
    """
    docs = conn_src.execute(sql, list(DF_TIPOS)).fetchall()
    print(f"Total de DFs 2024-2026 encontrados: {len(docs)}")

    t0 = time.time()
    total_raw_chars = 0
    total_chunks_gerados = 0
    chunks_novos = 0
    chunks_repetidos = 0
    chunks_com_secao = 0
    chunks_com_canonica = 0

    for i, (proto, cnpj, cat, tipo, assunto, dref, dent, txt) in enumerate(docs, 1):
        total_raw_chars += len(txt)
        txt_limpo = limpar(txt)
        secoes = extrair_secoes_documento(txt)
        tem_paginas = "\f" in txt
        cnpj_tok = re.sub(r"\D", "", cnpj)

        chunks = dividir_com_offsets(txt_limpo)
        total_chunks_gerados += len(chunks)

        for ordem, (chunk_txt, _) in enumerate(chunks):
            # Encontra a posição exata do trecho no texto original para mapear seção e página
            pedaco_busca = chunk_txt.strip().split("\n")[0][:50]
            offset = txt.find(pedaco_busca) if pedaco_busca else -1
            if offset < 0:
                offset = 0

            sec = encontrar_secao_do_offset(secoes, offset)
            s_num = sec.numero if sec else None
            s_tit = sec.titulo if sec else None
            s_can = sec.secao_canonica if sec else None
            pag = (1 + txt[:offset].count("\f")) if tem_paginas and offset >= 0 else None

            if s_num:
                chunks_com_secao += 1
            if s_can:
                chunks_com_canonica += 1

            h = hash_trecho(chunk_txt)
            row = conn_dst.execute(
                "SELECT chunk_id, data_referencia FROM chunks WHERE cnpj_companhia = ? AND hash = ?",
                (cnpj, h)
            ).fetchone()

            if row is None:
                cur = conn_dst.execute("""
                    INSERT INTO chunks (
                        cnpj_companhia, cnpj_tok, hash, texto, rep_protocolo, rep_ordem,
                        categoria, tipo, data_referencia, data_entrega, secao_num, secao_titulo,
                        secao_canonica, pagina
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (cnpj, cnpj_tok, h, chunk_txt, proto, ordem, cat, tipo, dref, dent,
                      s_num, s_tit, s_can, pag))
                cid = cur.lastrowid
                conn_dst.execute("INSERT INTO chunks_fts (rowid, texto, cnpj_tok, secao_canonica) VALUES (?,?,?,?)",
                                 (cid, chunk_txt, cnpj_tok, s_can))
                chunks_novos += 1
            else:
                cid = row[0]
                chunks_repetidos += 1
                if (dref or "") >= (row[1] or ""):
                    conn_dst.execute("""
                        UPDATE chunks SET rep_protocolo=?, rep_ordem=?, data_referencia=?, data_entrega=?,
                                          secao_num=?, secao_titulo=?, secao_canonica=?, pagina=?
                        WHERE chunk_id=?
                    """, (proto, ordem, dref, dent, s_num, s_tit, s_can, pag, cid))

            conn_dst.execute("INSERT OR REPLACE INTO chunk_docs (chunk_id, protocolo_entrega, ordem) VALUES (?,?,?)",
                             (cid, proto, ordem))

        if i % 200 == 0 or i == len(docs):
            conn_dst.commit()
            elapsed = time.time() - t0
            pct_sec = (chunks_com_secao / total_chunks_gerados * 100) if total_chunks_gerados else 0
            print(f"  {i}/{len(docs)} docs | Chunks novos: {chunks_novos} repetidos: {chunks_repetidos} | "
                  f"Secao: {pct_sec:.1f}% ({elapsed:.1f}s)", flush=True)

    conn_dst.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
    conn_dst.commit()

    total_tempo = time.time() - t0
    unique_chars = conn_dst.execute("SELECT SUM(length(texto)) FROM chunks").fetchone()[0] or 0
    tamanho_db_mb = os.path.getsize(dst_path) / (1024 * 1024)
    taxa_dedup = (1 - (chunks_novos / total_chunks_gerados)) * 100 if total_chunks_gerados else 0
    pct_secao = (chunks_com_secao / total_chunks_gerados * 100) if total_chunks_gerados else 0
    pct_can = (chunks_com_canonica / total_chunks_gerados * 100) if total_chunks_gerados else 0

    print("\n" + "=" * 60)
    print("RESULTADOS DO STRESS TEST (DFP + ITR 2024-2026)")
    print("=" * 60)
    print(f"Documentos processados:          {len(docs)}")
    print(f"Caracteres brutos originais:     {total_raw_chars / 1e6:.1f} MB")
    print(f"Caracteres únicos armazenados:   {unique_chars / 1e6:.1f} MB")
    print(f"Total de trechos gerados:        {total_chunks_gerados}")
    print(f"Trechos únicos:                  {chunks_novos}")
    print(f"Trechos repetidos (deduplicados):{chunks_repetidos}")
    print(f"Taxa de deduplicação:            {taxa_dedup:.1f}%")
    print(f"Trechos com seção identificada:  {chunks_com_secao}/{total_chunks_gerados} ({pct_secao:.1f}%) [Meta >= 85%]")
    print(f"Trechos com seção canônica:      {chunks_com_canonica}/{total_chunks_gerados} ({pct_can:.1f}%)")
    print(f"Tamanho do banco gerado (c/ FTS):{tamanho_db_mb:.1f} MB")
    
    # Projeção para todas as 7.255 DFs históricas da base
    fator_escala = 7255 / len(docs) if len(docs) else 1
    projecao_gb = (tamanho_db_mb * fator_escala) / 1024
    print(f"Projeção para toda a base (7.255 DFs): +{projecao_gb:.2f} GB [Teto <= 3.0 GB]")

    # ── Teste de recuperação de itens conhecidos ─────────────────────────────
    print("\n" + "-" * 60)
    print("TESTE DE RECUPERAÇÃO DE ITENS CONHECIDOS (Hit@5)")
    print("-" * 60)

    casos_conhecidos = [
        ("WEGE3", "84429695", "ir_csll", "alíquota nominal"),
        ("WEGE3", "84429695", "subvencoes", "subvenções"),
        ("TUPY3", "84683474", "ir_csll", "imposto de renda"),
        ("INTB3", "02916265", "subvencoes", "benefícios fiscais"),
        ("POMO3", "88611835", "ir_csll", "conciliação"),
        ("KEPL3", "88175344", "subvencoes", "subvenções"),
        ("EMBR3", "07689002", "ir_csll", "imposto de renda"),
        ("VALE3", "33592510", "imobilizado", "imobilizado"),
        ("PETR4", "33000167", "ir_csll", "alíquota efetiva"),
    ]

    hits1 = 0
    hits5 = 0
    tempos = []

    for ticker, cnpj_raiz, secao_alvo, termo in casos_conhecidos:
        t_busca = time.time()
        # Busca FTS com filtro em WHERE
        where_clauses = ["chunks_fts MATCH ?", "c.cnpj_tok LIKE ?"]
        params = [f'texto : ("{termo}")', f"{cnpj_raiz}%"]
        if secao_alvo:
            where_clauses.append("c.secao_canonica = ?")
            params.append(secao_alvo)

        sql_busca = f"""
            SELECT c.rep_protocolo, c.secao_num, c.secao_canonica, c.texto
            FROM chunks_fts JOIN chunks c ON c.chunk_id = chunks_fts.rowid
            WHERE {' AND '.join(where_clauses)}
            ORDER BY chunks_fts.rank
            LIMIT 5
        """
        res = conn_dst.execute(sql_busca, params).fetchall()
        dt = (time.time() - t_busca) * 1000
        tempos.append(dt)

        achou_top1 = False
        achou_top5 = False
        if res:
            achou_top5 = True
            if res[0][2] == secao_alvo:
                achou_top1 = True

        if achou_top1:
            hits1 += 1
        if achou_top5:
            hits5 += 1

        status = "HIT@1" if achou_top1 else ("HIT@5" if achou_top5 else "MISS")
        print(f"  {ticker:6s} | {secao_alvo:15s} | {termo:20s} -> {status:6s} ({dt:.1f} ms)")

    print(f"\nHit@1: {hits1}/{len(casos_conhecidos)} ({hits1/len(casos_conhecidos)*100:.1f}%)")
    print(f"Hit@5: {hits5}/{len(casos_conhecidos)} ({hits5/len(casos_conhecidos)*100:.1f}%)")
    print(f"Latência média de busca: {sum(tempos)/len(tempos):.2f} ms")

    conn_src.close()
    conn_dst.close()


if __name__ == "__main__":
    main()
