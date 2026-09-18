#!/usr/bin/env python3
"""
CVM Research MCP Server — acesso somente-leitura ao cvm_research.db.

Transporte padrão: stdio (o Claude Code / Claude desktop sobem o processo sob
demanda; nada fica rodando em background, sem launchd, sem porta).

Registro no Claude Code (rodar da raiz do projeto):
    claude mcp add cvm-research -s user -- \
        "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"

Claude desktop app (claude_desktop_config.json):
    "cvm-research": {
      "command": "/caminho/absoluto/cvm-research/.venv/bin/python",
      "args": ["/caminho/absoluto/cvm-research/scripts/mcp/cvm_mcp.py"]
    }

Modo HTTP (opcional, para clientes que só falam streamable-http):
    python scripts/mcp/cvm_mcp.py --http --port 8765
    → "cvm-research": {"type": "http", "url": "http://localhost:8765/mcp"}

Banco: por padrão <raiz do projeto>/cvm_research.db. Sobrescreva com CVM_DB_PATH.

Ferramentas:
    query(sql)            → SELECT ad-hoc (somente leitura, limite de linhas)
    list_tables()         → tabelas e views do banco
    describe_table(name)  → colunas e tipos de uma tabela/view
"""

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------- Config ----------
PROJECT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("CVM_DB_PATH", PROJECT_DIR / "cvm_research.db"))
MAX_ROWS = 500

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--http", action="store_true", help="usa transporte streamable-http em vez de stdio")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()

if not DB_PATH.exists():
    print(f"ERRO: banco não encontrado em {DB_PATH}", file=sys.stderr)
    print("Rode: bash setup.sh  (e os ingestores em scripts/ingest/)", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("cvm-research", stateless_http=True, host=args.host, port=args.port)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|PRAGMA)\b", re.I)


def get_db() -> sqlite3.Connection:
    # mode=ro: o SQLite recusa qualquer escrita mesmo que o SQL passe pelo filtro.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


# ---------- Tools ----------

@mcp.tool()
def query(sql: str) -> list[dict]:
    """Executa um SELECT no banco CVM Research (somente leitura, até 500 linhas).

    Tabelas principais: companies, ipe_docs, vlmo_movimentacoes, vlmo_posicao,
    recompra_programas, fre_capital_social, fre_posicao_acionaria,
    fre_remuneracao_orgao, demonstrativos_contabeis, notas_explicativas,
    consistency_runs, consistency_flags, cd_conta_ds_timeline.
    Views: vw_dre (trimestre isolado no ITR), vw_dre_acumulada, vw_balanco. Full-text: ipe_docs_fts, notas_explicativas_fts.
    consistency_flags: achados de consistência (layer=1 hierarchy_sum: nao_detalhado/pai_vazio/divergencia/
    divergencia_formula dentro de um documento; layer=2 cross_period: reapresentacao/reclassificacao entre filings;
    layer=3 granularity: renumerado/zero_padding/reclassificado_em_outros/reclassificado_em_irmao/divergencia_nao_explicada
    para linhas só num dos filings; layer=5 text_stability: ambiguo, fila de revisão da similaridade;
    cd_conta NULL = resumo do par; detalhe é JSON — use json_extract).
    cd_conta_ds_timeline: trilha de cada linha (pai + nome) entre filings consecutivos — renumerado/reformulacao/ambiguo/
    nova/removida com cd_conta_anterior (estavel não é gravada).
    Sempre identifique empresas pelo CNPJ (SELECT cnpj FROM companies WHERE ticker = ?).
    """
    s = sql.strip().rstrip(";")
    if not re.match(r"^(SELECT|WITH)\b", s, re.I) or _FORBIDDEN.search(s):
        raise ValueError("Apenas SELECT (ou WITH ... SELECT) é permitido.")
    conn = get_db()
    try:
        cur = conn.execute(s)
        rows = cur.fetchmany(MAX_ROWS + 1)
        out = [dict(r) for r in rows[:MAX_ROWS]]
        if len(rows) > MAX_ROWS:
            out.append({"_aviso": f"resultado truncado em {MAX_ROWS} linhas — use LIMIT/filtros"})
        return out
    finally:
        conn.close()


@mcp.tool()
def list_tables() -> list[dict]:
    """Lista tabelas e views do banco com a contagem de linhas."""
    conn = get_db()
    try:
        names = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE '%_fts_%' ORDER BY type, name"
        ).fetchall()
        out = []
        for name, typ in names:
            try:
                n = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error:
                n = None
            out.append({"name": name, "type": typ, "rows": n})
        return out
    finally:
        conn.close()


@mcp.tool()
def describe_table(table: str) -> list[dict]:
    """Retorna as colunas (nome, tipo, not null, pk) de uma tabela ou view."""
    if not _IDENT.match(table):
        raise ValueError("Nome de tabela inválido.")
    conn = get_db()
    try:
        cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        if not cols:
            raise ValueError(f"Tabela '{table}' não existe.")
        return [dict(c) for c in cols]
    finally:
        conn.close()


# ---------- Entry ----------

if __name__ == "__main__":
    if args.http:
        print(f"CVM MCP Server em http://{args.host}:{args.port}/mcp — banco: {DB_PATH}", file=sys.stderr)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio
