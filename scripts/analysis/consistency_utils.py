"""
Helpers compartilhados pelas camadas de consistência (scripts/analysis/).

Convenções:
  - Nunca alteram demonstrativos_contabeis: leem dela e gravam apenas em
    consistency_runs / consistency_flags.
  - "Documento" (filing) = (cnpj_companhia, fonte, tipo_doc, data_referencia)
    na versão máxima. "Período" = (periodo_ini, periodo_fim), com
    periodo_ini = COALESCE(dt_ini_exerc, 'NA') — BPA/BPP são posição na data.
  - Tolerância por linha: max(tol_abs, tol_rel × |ref|), piso R$ 1.000
    (plano-mãe: na DRE o piso sobe o acerto de 81% para 87,6%).
"""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from utils import get_db  # noqa: E402  — reaproveita DATABASE_URL, WAL e foreign_keys

__all__ = ["get_db", "tolerancia", "parent_code", "total_codes", "latest_rows",
           "new_run", "finish_run", "write_flags", "clear_flags", "add_common_args",
           "TIPOS_DOC", "FLAG_COLS"]

TIPOS_DOC = ["BPA", "BPP", "DRE", "DFC_MI", "DVA"]

# Conta-total de nível 1/2 por tipo_doc (plano-mãe, Camada 2, regra 3).
# DRE: 3.01 e 3.11 existem em todos os planos de contas; qualquer uma divergindo
# classifica o par como reapresentação.
# DVA: o código varia por plano (7.07 industrial, 7.08 bancos, 7.10 seguradoras);
# total_codes() resolve pelo nome dentro do próprio documento.
TOTAL_CODES = {
    "BPA":    ["1"],
    "BPP":    ["2"],
    "DRE":    ["3.11", "3.01"],
    "DFC_MI": ["6.05"],
    "DVA":    ["7.07"],
}
DVA_TOTAL_DS = "valor adicionado total a distribuir"


# ── Regras numéricas ─────────────────────────────────────────────────────────

def tolerancia(valor_ref, tol_abs: float = 1000.0, tol_rel: float = 0.005):
    """max(tol_abs, tol_rel × |valor_ref|). Aceita escalar ou pd.Series (sem NaN)."""
    return np.maximum(tol_abs, tol_rel * np.abs(valor_ref))


def parent_code(cd_conta: str):
    """'3.04.05.06' → '3.04.05'; '1' → None."""
    return cd_conta.rsplit(".", 1)[0] if "." in cd_conta else None


def total_codes(tipo_doc: str, doc: pd.DataFrame) -> list[str]:
    """Códigos da conta-total do tipo_doc. Para DVA procura o nome nas contas de
    nível 2 do documento (`doc` precisa das colunas cd_conta e ds_conta)."""
    if tipo_doc != "DVA":
        return TOTAL_CODES[tipo_doc]
    nivel2 = doc[doc["cd_conta"].astype(str).str.count(r"\.") == 1]
    nomes = nivel2["ds_conta"].fillna("").astype(str).str.strip().str.lower()
    achados = nivel2.loc[nomes.str.startswith(DVA_TOTAL_DS), "cd_conta"].unique().tolist()
    return achados or TOTAL_CODES["DVA"]


# ── Leitura ──────────────────────────────────────────────────────────────────

_LATEST_SQL = """
WITH versao_max AS (
    SELECT cnpj_companhia, fonte, tipo_doc, data_referencia, MAX(versao) AS versao
    FROM demonstrativos_contabeis
    WHERE 1 = 1 {filtros}
    GROUP BY cnpj_companhia, fonte, tipo_doc, data_referencia
)
SELECT d.cnpj_companhia, d.fonte, d.tipo_doc, d.data_referencia, d.versao,
       d.ordem_exercicio,
       COALESCE(d.dt_ini_exerc, 'NA') AS periodo_ini,
       d.dt_fim_exerc                 AS periodo_fim,
       d.cd_conta, d.ds_conta, d.vl_conta, d.st_conta_fixa
FROM demonstrativos_contabeis d
JOIN versao_max v
  ON  d.cnpj_companhia = v.cnpj_companhia AND d.fonte = v.fonte
  AND d.tipo_doc = v.tipo_doc AND d.data_referencia = v.data_referencia
  AND d.versao = v.versao
ORDER BY d.cnpj_companhia, d.tipo_doc, d.data_referencia, d.fonte, d.ordem_exercicio, d.cd_conta
"""


def latest_rows(conn: sqlite3.Connection, cnpj=None, tipo_doc=None, fonte=None,
                desde=None, ate=None) -> pd.DataFrame:
    """Linhas de demonstrativos_contabeis na versão máxima **por documento**
    (cnpj, fonte, tipo_doc, data_referencia), com periodo_ini/periodo_fim.
    desde/ate são anos e filtram a data_referencia do FILING — um filing de
    `desde` ainda carrega períodos Penúltimo do ano anterior."""
    filtros, params = [], []
    if cnpj:
        filtros.append("AND cnpj_companhia = ?"); params.append(cnpj)
    if tipo_doc:
        filtros.append("AND tipo_doc = ?"); params.append(tipo_doc)
    if fonte:
        filtros.append("AND fonte = ?"); params.append(fonte)
    if desde:
        filtros.append("AND data_referencia >= ?"); params.append(f"{desde}-01-01")
    if ate:
        filtros.append("AND data_referencia <= ?"); params.append(f"{ate}-12-31")
    sql = _LATEST_SQL.format(filtros=" ".join(filtros))
    return pd.read_sql_query(sql, conn, params=params)


# ── Escrita (runs / flags) ───────────────────────────────────────────────────

FLAG_COLS = [
    "run_id", "layer", "check_type", "classificacao", "severity",
    "cnpj_companhia", "tipo_doc", "cd_conta", "cd_conta_pai", "ds_conta",
    "periodo_ini", "periodo_fim",
    "fonte_ref", "data_ref", "ordem_ref", "fonte_cmp", "data_cmp", "ordem_cmp",
    "valor_ref", "valor_cmp", "diff_abs", "diff_rel", "detalhe",
]


def new_run(conn, layer: int, check_type: str, escopo: str, script_args: dict) -> str:
    run_id = f"{check_type}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO consistency_runs (run_id, layer, check_type, escopo, script_args) VALUES (?,?,?,?,?)",
        (run_id, layer, check_type, escopo, json.dumps(script_args, ensure_ascii=False, default=str)),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id: str, total_checked: int, total_flagged: int) -> None:
    conn.execute(
        "UPDATE consistency_runs SET finished_at = datetime('now'), total_checked = ?, total_flagged = ? "
        "WHERE run_id = ?",
        (total_checked, total_flagged, run_id),
    )
    conn.commit()


def _sql_value(v):
    """NaN/numpy → tipos nativos/NULL; dict/list → JSON."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    return v


def write_flags(conn, run_id: str, flags: list[dict]) -> int:
    """Insere flags (dicts com chaves de FLAG_COLS; ausentes viram NULL). Retorna n."""
    if not flags:
        return 0
    rows = [tuple(_sql_value(run_id if c == "run_id" else f.get(c)) for c in FLAG_COLS) for f in flags]
    sql = (f"INSERT INTO consistency_flags ({','.join(FLAG_COLS)}) "
           f"VALUES ({','.join('?' * len(FLAG_COLS))})")
    try:
        conn.executemany(sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def clear_flags(conn, layer: int, check_type: str, cnpj: str, tipo_doc: str | None = None) -> int:
    """Apaga as flags anteriores do escopo (layer, check_type, cnpj[, tipo_doc]). Retorna n."""
    sql = "DELETE FROM consistency_flags WHERE layer = ? AND check_type = ? AND cnpj_companhia = ?"
    params: list = [layer, check_type, cnpj]
    if tipo_doc:
        sql += " AND tipo_doc = ?"
        params.append(tipo_doc)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


# ── CLI ──────────────────────────────────────────────────────────────────────

def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Argumentos comuns a todas as camadas (mesmo estilo de ingest_dfp.py)."""
    parser.add_argument("--cnpj", help="CNPJ no formato 00.000.000/0001-00 (só essa empresa)")
    parser.add_argument("--tipo-doc", dest="tipo_doc", choices=TIPOS_DOC, help="Só esse tipo de demonstrativo")
    parser.add_argument("--desde", type=int, metavar="ANO", help="data_referencia do filing >= ANO-01-01")
    parser.add_argument("--ate", type=int, metavar="ANO", help="data_referencia do filing <= ANO-12-31")
    parser.add_argument("--full", action="store_true", help="Confirma a execução na base inteira (sem --cnpj)")
    parser.add_argument("--tol-abs", dest="tol_abs", type=float, default=1000.0,
                        help="Tolerância absoluta em R$ (padrão 1000)")
    parser.add_argument("--tol-rel", dest="tol_rel", type=float, default=0.005,
                        help="Tolerância relativa sobre |ref| (padrão 0.005 = 0,5%%)")
