"""
Aplica utils.repair_pdf_text ao texto já extraído (ipe_docs e notas_explicativas).

Script de uso único: extract_pdf.py e ingest_notas_explicativas.py já reparam o
texto na extração; este conserta o que entrou antes. Ver o comentário de
repair_pdf_text em utils.py para o que é reparado e o que fica como está ("(cid:N)"
de fonte Identity-H não tem conserto sem a fonte).

Sem --aplicar só conta: quantas linhas mudariam, "(cid:" antes/depois e exemplos.
Com --aplicar grava em lotes (texto_extraido e chars_extraidos), reconstrói os dois
índices FTS5 e mede de novo. Antes de sobrescrever, o texto original de cada linha
alterada vai para repair_text_encoding_backup_<data>.db, ao lado do banco.

Uso:
  python repair_text_encoding.py              # dry-run
  python repair_text_encoding.py --aplicar
  python repair_text_encoding.py --aplicar --lote 200

Requer DATABASE_URL=sqlite:///cvm_research.db no .env.
"""
import argparse
import sqlite3
from datetime import date
from pathlib import Path

from utils import get_db, repair_pdf_text

TABELAS = {
    # tabela: (chave, índice FTS, SET extra)
    "ipe_docs":           ("protocolo_entrega", "ipe_docs_fts", ""),
    "notas_explicativas": ("id", "notas_explicativas_fts", ", updated_at = datetime('now')"),
}
TERMOS_FTS = ("solicitacao", "informacoes")


def medir(conn: sqlite3.Connection) -> dict:
    """Linhas com "(cid:" e acertos no FTS por termo, por tabela."""
    m = {}
    for tabela, (_, fts, _) in TABELAS.items():
        m[(tabela, "cid")] = conn.execute(
            f"SELECT COUNT(*) FROM {tabela} WHERE texto_extraido LIKE '%(cid:%'"
        ).fetchone()[0]
        for termo in TERMOS_FTS:
            m[(tabela, termo)] = conn.execute(
                f"SELECT COUNT(*) FROM {fts} WHERE {fts} MATCH ?", (termo,)
            ).fetchone()[0]
    return m


def imprimir(titulo: str, m: dict, depois: dict | None = None) -> None:
    print(titulo)
    for (tabela, chave), v in m.items():
        rotulo = "linhas com (cid:" if chave == "cid" else f"FTS '{chave}'"
        extra = f" → {depois[(tabela, chave)]:>7,}" if depois else ""
        print(f"  {tabela:<20} {rotulo:<22} {v:>7,}{extra}")


def varrer(conn: sqlite3.Connection, tabela: str, lote: int, aplicar: bool,
           backup: sqlite3.Connection | None = None, exemplos: int = 3) -> dict:
    """Percorre a tabela por chave (keyset) e repara lote a lote."""
    chave, _, set_extra = TABELAS[tabela]
    r = {"lidas": 0, "mudariam": 0, "cid_antes": 0, "cid_depois": 0, "exemplos": []}
    ultimo = "" if chave == "protocolo_entrega" else -1
    while True:
        linhas = conn.execute(
            f"""SELECT {chave}, texto_extraido FROM {tabela}
                 WHERE texto_extraido IS NOT NULL AND {chave} > ?
                 ORDER BY {chave} LIMIT ?""",
            (ultimo, lote),
        ).fetchall()
        if not linhas:
            break
        ultimo = linhas[-1][0]
        r["lidas"] += len(linhas)
        updates = []
        for k, texto in linhas:
            novo = repair_pdf_text(texto)
            if novo == texto:
                continue
            r["mudariam"] += 1
            r["cid_antes"] += "(cid:" in texto
            r["cid_depois"] += "(cid:" in novo
            if len(r["exemplos"]) < exemplos:
                r["exemplos"].append((k, texto[:160], novo[:160]))
            updates.append((novo, len(novo), k, texto))
        if aplicar and updates:
            if backup is not None:
                backup.executemany(
                    "INSERT OR IGNORE INTO original (tabela, chave, texto_extraido) VALUES (?, ?, ?)",
                    [(tabela, str(k), texto) for _, _, k, texto in updates],
                )
                backup.commit()
            conn.executemany(
                f"UPDATE {tabela} SET texto_extraido = ?, chars_extraidos = ?{set_extra} "
                f"WHERE {chave} = ?",
                [u[:3] for u in updates],
            )
            conn.commit()
    return r


def main(aplicar: bool = False, lote: int = 500) -> None:
    conn = get_db()
    antes = medir(conn)
    imprimir("Antes:", antes)

    backup = None
    if aplicar:
        banco = Path(conn.execute("PRAGMA database_list").fetchone()[2])
        caminho = banco.with_name(f"repair_text_encoding_backup_{date.today():%Y-%m-%d}.db")
        backup = sqlite3.connect(caminho)
        backup.execute("CREATE TABLE IF NOT EXISTS original "
                       "(tabela TEXT, chave TEXT, texto_extraido TEXT, PRIMARY KEY (tabela, chave))")
        print(f"\nBackup do texto original: {caminho}")

    for tabela in TABELAS:
        r = varrer(conn, tabela, lote, aplicar, backup)
        verbo = "reparadas" if aplicar else "mudariam"
        print(f"\n{tabela}: {r['lidas']:,} com texto, {r['mudariam']:,} {verbo} "
              f"((cid: nelas: {r['cid_antes']:,} → {r['cid_depois']:,})")
        for k, a, d in r["exemplos"]:
            print(f"  [{k}]\n    antes:  {a!r}\n    depois: {d!r}")

    if not aplicar:
        print("\nDry-run: nada gravado. Rode com --aplicar para gravar e reconstruir o FTS.")
        return

    for tabela, (_, fts, _) in TABELAS.items():
        print(f"\nReconstruindo {fts}...")
        conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")
        conn.commit()
    print()
    imprimir("Antes → depois:", antes, medir(conn))


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Repara (cid:N) e StandardEncoding no texto já extraído e reconstrói o FTS."
    )
    p.add_argument("--aplicar", action="store_true",
                   help="Grava as correções (sem isto, só conta)")
    p.add_argument("--lote", type=int, default=500, help="Linhas por lote (default: 500)")
    args = p.parse_args()
    main(args.aplicar, args.lote)
