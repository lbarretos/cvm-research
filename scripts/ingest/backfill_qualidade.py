"""Backfill da métrica de qualidade do texto extraído (Etapa 9, item 9.7).

Avalia o texto_extraido existente no banco, calcula a qualidade por página/bloco e
grava `qualidade` ('ok', 'parcial', 'ruim') e `texto_qualidade` (JSON) em `ipe_docs`.
Não acessa a rede (puramente local/SQLite).

Uso:
  python backfill_qualidade.py --so-df               # só demonstrações financeiras (DFP, ITR...)
  python backfill_qualidade.py --todos               # todos os documentos do IPE com texto
  python backfill_qualidade.py --limite 100          # lote pequeno para teste
  python backfill_qualidade.py --forcar              # reavalia quem já tem qualidade preenchida
"""
import argparse
import sys
import time
from pathlib import Path

# adiciona a pasta scripts/ingest ao path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qualidade_texto import avaliar_documento
from utils import get_db


def ensure_qualidade_columns(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ipe_docs)").fetchall()}
    if "qualidade" not in cols:
        conn.execute("ALTER TABLE ipe_docs ADD COLUMN qualidade TEXT")
    if "texto_qualidade" not in cols:
        conn.execute("ALTER TABLE ipe_docs ADD COLUMN texto_qualidade TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ipe_docs_qualidade ON ipe_docs (qualidade) WHERE qualidade IS NOT NULL")
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--so-df", action="store_true", help="Avalia apenas demonstrações financeiras (DFP/ITR)")
    ap.add_argument("--todos", action="store_true", help="Avalia todos os documentos com texto")
    ap.add_argument("--limite", type=int, default=None, help="Limite de documentos a processar")
    ap.add_argument("--forcar", action="store_true", help="Reprocessa mesmo quem já tem qualidade preenchida")
    ap.add_argument("--lote", type=int, default=250, help="Tamanho do lote por commit")
    args = ap.parse_args()

    conn = get_db()
    ensure_qualidade_columns(conn)

    where = ["texto_extraido IS NOT NULL"]
    if not args.forcar:
        where.append("qualidade IS NULL")

    if args.so_df or (not args.todos and not args.so_df):
        where.append("(categoria = 'Dados Econômico-Financeiros' AND (tipo LIKE 'Demonstrações Financeiras%' OR tipo = 'Press-release'))")

    sql = f"SELECT protocolo_entrega, texto_extraido FROM ipe_docs WHERE {' AND '.join(where)}"
    if args.limite:
        sql += f" LIMIT {args.limite}"

    total_pendentes = conn.execute(f"SELECT COUNT(*) FROM ipe_docs WHERE {' AND '.join(where)}").fetchone()[0]
    total_a_rodar = min(total_pendentes, args.limite) if args.limite else total_pendentes
    print(f"Documentos a processar: {total_a_rodar} (de {total_pendentes} pendentes)")
    if total_a_rodar == 0:
        return

    cur = conn.cursor()
    cur.execute(sql)

    stats = {"ok": 0, "parcial": 0, "ruim": 0}
    lote_updates = []
    t0 = time.time()
    processados = 0

    while True:
        rows = cur.fetchmany(args.lote)
        if not rows:
            break

        for proto, txt in rows:
            status, info_json = avaliar_documento(txt)
            stats[status] += 1
            lote_updates.append((status, info_json, proto))

        conn.executemany(
            "UPDATE ipe_docs SET qualidade = ?, texto_qualidade = ? WHERE protocolo_entrega = ?",
            lote_updates,
        )
        conn.commit()
        processados += len(lote_updates)
        lote_updates.clear()

        elapsed = time.time() - t0
        taxa = processados / max(elapsed, 0.1)
        print(f"  {processados}/{total_a_rodar} docs ({processados/total_a_rodar*100:.1f}%) | "
              f"ok: {stats['ok']}, parcial: {stats['parcial']}, ruim: {stats['ruim']} | "
              f"{taxa:.1f} docs/s")

    dur = time.time() - t0
    print(f"\nFinalizado em {dur:.1f}s: {processados} docs avaliados.")
    print(f"  ok: {stats['ok']} ({stats['ok']/max(processados,1)*100:.1f}%)")
    print(f"  parcial: {stats['parcial']} ({stats['parcial']/max(processados,1)*100:.1f}%)")
    print(f"  ruim: {stats['ruim']} ({stats['ruim']/max(processados,1)*100:.1f}%)")
    conn.close()


if __name__ == "__main__":
    main()
