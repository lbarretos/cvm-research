"""
Helpers compartilhados pelas camadas de consistência (scripts/analysis/).

Convenções:
  - Nunca alteram demonstrativos_contabeis: leem dela e gravam apenas em
    consistency_runs / consistency_flags.
  - "Documento" (filing) = (cnpj_companhia, fonte, tipo_doc, data_referencia)
    na versão máxima. "Período" = (periodo_ini, periodo_fim), com
    periodo_ini = COALESCE(dt_ini_exerc, 'NA') — BPA/BPP são posição na data.
  - Tolerância por linha: max(tol_abs, tol_rel × |ref|), piso R$ 1.000 e 1%
    relativo (decisão do usuário em 2026-09-17; plano-mãe: na DRE o piso sobe
    o acerto de 81% para 87,6%).
"""
import argparse
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from utils import get_db  # noqa: E402  — reaproveita DATABASE_URL, WAL e foreign_keys

__all__ = ["get_db", "tolerancia", "parent_code", "parse_hierarchy", "total_codes", "latest_rows",
           "normalize_text", "is_outros", "text_similarity", "OUTROS_RE",
           "cnpjs_financeiros", "new_run", "finish_run", "write_flags", "clear_flags", "add_common_args",
           "TIPOS_DOC", "FLAG_COLS", "EXCECOES_SOMA", "FORMULAS_NIVEL2", "SETOR_FINANCEIRO"]

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

# ── Camada 1 (soma hierárquica) ──────────────────────────────────────────────
# Exceções estruturais à regra "pai = Σ filhos diretos" (plano-mãe, Fase 2):
#   'saldo': 6.05 = 6.05.02 (saldo final) − 6.05.01 (saldo inicial); bate em 99,8% dos DFPs.
#   'skip' : 3.99 (lucro por ação) e descendentes — filhos ON/PN não somam.
EXCECOES_SOMA = {
    ("DFC_MI", "6.05"): "saldo",
    ("DRE", "3.99"):    "skip",
}

# Fórmulas fixas de nível 2 (substituem a calibração empírica do plano original;
# acerto de 99,8–100% nos DFPs 2019–2024 não financeiros). Só para empresas fora
# de companies.setor = 'Financeiro' (plano COSIF diverge do nível 2 em diante).
# Termo ausente do documento conta como 0; alvo ausente → fórmula não é checada.
FORMULAS_NIVEL2 = {
    "DRE":    [("3.03", ["3.01", "3.02"]), ("3.05", ["3.03", "3.04"]), ("3.07", ["3.05", "3.06"]),
               ("3.09", ["3.07", "3.08"]), ("3.11", ["3.09", "3.10"])],
    "DFC_MI": [("6.05", ["6.01", "6.02", "6.03", "6.04"])],
}
SETOR_FINANCEIRO = "Financeiro"


# ── Regras numéricas ─────────────────────────────────────────────────────────

def tolerancia(valor_ref, tol_abs: float = 1000.0, tol_rel: float = 0.01):
    """max(tol_abs, tol_rel × |valor_ref|). Aceita escalar ou pd.Series (sem NaN)."""
    return np.maximum(tol_abs, tol_rel * np.abs(valor_ref))


def parent_code(cd_conta: str):
    """'3.04.05.06' → '3.04.05'; '1' → None."""
    return cd_conta.rsplit(".", 1)[0] if "." in cd_conta else None


def parse_hierarchy(codes) -> dict[str, list[str]]:
    """{pai: [filhos diretos]} só para pais PRESENTES em `codes` (a DRE não tem
    conta '3', então 3.01 não tem pai; 3.01.01 tem). Preserva a ordem de entrada
    e ignora duplicatas."""
    presentes = list(dict.fromkeys(codes))
    conjunto = set(presentes)
    filhos: dict[str, list[str]] = {}
    for cd in presentes:
        pai = parent_code(cd)
        if pai is not None and pai in conjunto:
            filhos.setdefault(pai, []).append(cd)
    return filhos


# ── Texto (Camadas 3, 4 e 5) ─────────────────────────────────────────────────
# "Outros"/"Outras"/"Outro"/"Demais" como palavra inteira sobre texto normalizado.
# `\boutr` do plano original casava "outorgadas" (148 linhas no BPP 2024).
OUTROS_RE = re.compile(r"\b(outr[oa]s?|demais)\b")


def normalize_text(s) -> str:
    """Minúsculas, sem acentos, só [a-z0-9 ], espaços colapsados; None/NaN → ''."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def is_outros(ds_conta) -> bool:
    return bool(OUTROS_RE.search(normalize_text(ds_conta)))


def text_similarity(a, b) -> float:
    """Similaridade em [0, 1] entre dois nomes de conta (Camada 4): difflib sobre o
    texto normalizado, tomando o maior entre a ordem original e os tokens ordenados
    (token-sort), para que "Empréstimos e Financiamentos" ≈ "Financiamentos e
    Empréstimos". Vazio de um lado → 0.0."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    direto = difflib.SequenceMatcher(None, na, nb).ratio()
    ordenado = difflib.SequenceMatcher(None, " ".join(sorted(na.split())), " ".join(sorted(nb.split()))).ratio()
    return max(direto, ordenado)


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


def cnpjs_financeiros(conn: sqlite3.Connection) -> set[str]:
    """CNPJs com companies.setor = 'Financeiro' (plano COSIF): sem fórmulas de nível 2."""
    return {r[0] for r in conn.execute("SELECT cnpj FROM companies WHERE setor = ?", (SETOR_FINANCEIRO,))}


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
    parser.add_argument("--tol-rel", dest="tol_rel", type=float, default=0.01,
                        help="Tolerância relativa sobre |ref| (padrão 0.01 = 1%%)")
