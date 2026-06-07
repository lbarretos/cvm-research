#!/usr/bin/env python3
"""
CVM Research MCP Server — HTTP streamable transport
Roda como processo independente, fora do sandbox do Claude.app.

Uso:
    python3 scripts/mcp/cvm_mcp.py          # porta 8765 (default)
    python3 scripts/mcp/cvm_mcp.py --port 9000

Config no claude_desktop_config.json:
    "cvm-research": {
      "type": "http",
      "url": "http://localhost:8765/mcp"
    }
"""

import argparse
import sqlite3
import os
from pathlib import Path

# Parse args antes de instanciar o FastMCP (host/port vão no construtor)
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--host", default="127.0.0.1")
args = parser.parse_args()

from mcp.server.fastmcp import FastMCP

# ---------- Config ----------
DEFAULT_DB = Path(__file__).resolve().parents[2] / "cvm_research.db"
DB_PATH = os.environ.get("CVM_DB_PATH", str(DEFAULT_DB))

mcp = FastMCP(
    "cvm-research",
    stateless_http=True,
    host=args.host,
    port=args.port,
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- Tools ----------

@mcp.tool()
def query(sql: str) -> list[dict]:
    """Execute uma query SQL de leitura no banco CVM Research."""
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("Apenas SELECT é permitido.")
    with get_db() as conn:
        cur = conn.execute(sql)
        return [dict(row) for row in cur.fetchall()]


@mcp.tool()
def list_tables() -> list[str]:
    """Lista todas as tabelas disponíveis no banco."""
    with get_db() as conn:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [row[0] for row in cur.fetchall()]


@mcp.tool()
def describe_table(table: str) -> list[dict]:
    """Retorna o schema (colunas e tipos) de uma tabela."""
    with get_db() as conn:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [dict(row) for row in cur.fetchall()]


# ---------- Entry ----------

if __name__ == "__main__":
    print(f"CVM MCP Server rodando em http://{args.host}:{args.port}/mcp")
    print(f"Banco: {DB_PATH}")
    mcp.run(transport="streamable-http")
