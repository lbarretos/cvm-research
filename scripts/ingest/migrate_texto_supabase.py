"""
Migra texto_extraido do Supabase → PostgreSQL local.

Lê todos os documentos com texto extraído do Supabase e atualiza
as colunas texto_extraido, chars_extraidos, extraido_em e extracao_falhou
no banco local.

Uso:
  python migrate_texto_supabase.py            # migra e exibe relatório
  python migrate_texto_supabase.py --dry-run  # só conta, não escreve

Requer no .env:
  DATABASE_URL=postgresql://localhost/cvm_research
  SUPABASE_URL=https://xxxx.supabase.co
  SUPABASE_KEY=eyJ...
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[2] / ".env")

import os
import psycopg2
from supabase import create_client

BATCH = 500  # linhas por requisição Supabase


def main(dry_run: bool = False) -> None:
    # ── conexões ──────────────────────────────────────────────────────────────
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    db_url = os.environ.get("DATABASE_URL", "")

    if not sb_url or not sb_key:
        print("ERRO: SUPABASE_URL e SUPABASE_KEY precisam estar no .env", file=sys.stderr)
        sys.exit(1)
    if not db_url:
        print("ERRO: DATABASE_URL precisa estar no .env", file=sys.stderr)
        sys.exit(1)

    print(f"Supabase: {sb_url}")
    print(f"Local: {db_url}")
    print(f"Modo: {'DRY-RUN (sem escrita)' if dry_run else 'MIGRAÇÃO REAL'}\n")

    sb = create_client(sb_url, sb_key)
    conn = psycopg2.connect(db_url)

    # ── busca total no Supabase ───────────────────────────────────────────────
    total_resp = (
        sb.table("ipe_docs")
          .select("protocolo_entrega", count="exact")
          .not_.is_("texto_extraido", "null")
          .execute()
    )
    total = total_resp.count
    print(f"Documentos com texto no Supabase: {total}")

    if total == 0:
        print("Nada a migrar.")
        conn.close()
        return

    # ── migração em lotes ─────────────────────────────────────────────────────
    migrados = 0
    skipped = 0
    offset = 0

    while offset < total:
        resp = (
            sb.table("ipe_docs")
              .select("protocolo_entrega, texto_extraido, chars_extraidos, extraido_em, extracao_falhou")
              .not_.is_("texto_extraido", "null")
              .range(offset, offset + BATCH - 1)
              .execute()
        )
        rows = resp.data
        if not rows:
            break

        if not dry_run:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        """
                        UPDATE ipe_docs
                        SET texto_extraido  = %s,
                            chars_extraidos = %s,
                            extraido_em     = %s,
                            extracao_falhou = %s
                        WHERE protocolo_entrega = %s
                          AND texto_extraido IS NULL
                        """,
                        (
                            row["texto_extraido"],
                            row["chars_extraidos"],
                            row.get("extraido_em"),
                            row.get("extracao_falhou", False),
                            row["protocolo_entrega"],
                        ),
                    )
                    if cur.rowcount:
                        migrados += 1
                    else:
                        skipped += 1
            conn.commit()

        offset += len(rows)
        print(f"  Lote {offset}/{total} processado...", end="\r")

    print()

    # ── relatório ─────────────────────────────────────────────────────────────
    if dry_run:
        print(f"\nDRY-RUN: {total} documentos seriam migrados.")
    else:
        print(f"\nMigração concluída:")
        print(f"  ✅ Migrados:       {migrados}")
        print(f"  ⏭  Já existiam:   {skipped} (texto_extraido já preenchido localmente)")

        # verificação pós-migração
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), SUM(chars_extraidos) FROM ipe_docs WHERE texto_extraido IS NOT NULL")
            row = cur.fetchone()
            print(f"\nLocal após migração:")
            print(f"  Docs com texto: {row[0]}")
            print(f"  Total chars:    {row[1]:,}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Só conta, não escreve")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
