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
    resolve_company(texto) → ticker, nome parcial ou CNPJ → até 5 empresas (ou aviso de que não está na base)
    query(sql)             → SELECT ad-hoc (somente leitura); saída tabular {colunas, linhas}
    list_tables()          → tabelas (com contagem de linhas) e views
    describe_table(name)   → colunas e tipos de uma tabela/view

Toda resposta cabe em MAX_RESPONSE_CHARS; o que passar é cortado com aviso.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------- Config ----------
PROJECT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("CVM_DB_PATH", PROJECT_DIR / "cvm_research.db"))
MAX_ROWS = 500
MAX_CELL_CHARS = 25_000  # ipe_docs.texto_extraido chega a 12 milhões de caracteres; uma célula cabe no orçamento da resposta
QUERY_TIMEOUT_S = 20.0
MAX_RESPONSE_CHARS = 30_000  # orçamento por chamada: o contexto do LLM é o recurso escasso

mcp = FastMCP("cvm-research", stateless_http=True)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Literais, identificadores entre aspas e comentários saem antes do filtro de palavras:
# MATCH 'update' e LIKE '%create%' são SELECTs válidos. replace() é função, só REPLACE INTO é bloqueado.
_LITERAIS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]*\]|--[^\n]*|/\*.*?(?:\*/|$)", re.S)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|VACUUM|PRAGMA|REINDEX|ANALYZE)\b"
    r"|\bREPLACE\s+INTO\b",
    re.I,
)

# A guarda de verdade: o SQLite pergunta ao authorizer por cada operação ao compilar o
# statement. Só leitura passa; ATTACH (que abriria outro arquivo), PRAGMA e escrita são negados.
# Exceção: PRAGMA data_version, que o FTS5 roda por dentro a cada MATCH (só lê um contador).
_PERMITIDAS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
               getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


def _authorizer(action, arg1, arg2, dbname, source):
    if action in _PERMITIDAS or (action == sqlite3.SQLITE_PRAGMA and arg1 == "data_version" and arg2 is None):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def get_db() -> sqlite3.Connection:
    # mode=ro: o SQLite recusa qualquer escrita mesmo que o SQL passe pelo filtro.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _com_prazo(conn: sqlite3.Connection) -> float:
    """Aborta qualquer statement da conexão depois de QUERY_TIMEOUT_S; devolve o instante-limite."""
    prazo = time.monotonic() + QUERY_TIMEOUT_S
    conn.set_progress_handler(lambda: time.monotonic() > prazo, 10_000)
    return prazo


def _cortar(v):
    if isinstance(v, str) and len(v) > MAX_CELL_CHARS:
        return (v[:MAX_CELL_CHARS]
                + f"…[truncado: {len(v)} chars; use substr(col, inicio, tamanho) ou snippet() do FTS]")
    return v


def _tabular(colunas: list[str], linhas: list[list], aviso: str | None = None) -> dict:
    """{colunas, linhas} em vez de um dict por linha (o nome de cada coluna não se repete).
    Corta as linhas finais até caber em MAX_RESPONSE_CHARS e diz quantas ficaram de fora."""
    total = len(linhas)
    usados = len(json.dumps(colunas, ensure_ascii=False))
    mantidas = []
    for l in linhas:
        n = len(json.dumps(l, ensure_ascii=False, default=str))
        if mantidas and usados + n > MAX_RESPONSE_CHARS:
            break
        # uma única linha maior que o orçamento: as células já foram cortadas em MAX_CELL_CHARS;
        # corta de novo para o resultado não estourar o contexto
        if not mantidas and n > MAX_RESPONSE_CHARS:
            l = [_cortar_para(v, max(200, MAX_RESPONSE_CHARS // max(len(l), 1))) for v in l]
            n = len(json.dumps(l, ensure_ascii=False, default=str))
        mantidas.append(l)
        usados += n
    out = {"colunas": colunas, "linhas": mantidas}
    avisos = [aviso] if aviso else []
    if len(mantidas) < total:
        avisos.append(f"resposta cortada em {len(mantidas)} de {total} linhas para caber em "
                      f"{MAX_RESPONSE_CHARS} caracteres: restrinja colunas/filtros ou use LIMIT")
    if avisos:
        out["aviso"] = "; ".join(avisos)
    return out


def _cortar_para(v, n: int):
    if isinstance(v, str) and len(v) > n:
        return v[:n] + f"…[truncado: {len(v)} chars; use substr(col, inicio, tamanho)]"
    return v


# ---------- Tools ----------

@mcp.tool()
def query(sql: str) -> dict:
    """Executa um SELECT no banco CVM Research (somente leitura, até 500 linhas).
    Devolve {"colunas": [...], "linhas": [[...]], "aviso"?}; o aviso diz quando o resultado foi cortado.
    Para achar a empresa use resolve_company (não precisa de SQL).

    Tabelas principais: companies, ipe_docs, vlmo_movimentacoes, vlmo_posicao,
    recompra_programas, fre_capital_social, fre_posicao_acionaria,
    fre_remuneracao_orgao, demonstrativos_contabeis, notas_explicativas,
    consistency_runs, consistency_flags, cd_conta_ds_timeline, demonstrativos_trimestrais.
    Views: vw_dre (trimestre isolado no ITR), vw_dre_acumulada, vw_balanco — só plano padrão, NULL em banco e
    seguradora (coluna plano_contas); vw_dre_financeiro (bancos), vw_dre_seguradora, vw_plano_contas,
    vw_acionistas_diretos (acionistas diretos no FRE mais recente). Full-text: ipe_docs_fts, notas_explicativas_fts.
    fre_posicao_acionaria mistura acionistas diretos e a cadeia de controle das holdings:
    id_acionista_relacionado NULL = direto; preenchido = percentual sobre o capital da holding, não da companhia.
    consistency_flags: achados de consistência (layer=1 hierarchy_sum: nao_detalhado/pai_vazio/divergencia/
    divergencia_formula dentro de um documento; layer=2 cross_period: reapresentacao/reclassificacao entre filings;
    layer=3 granularity: renumerado/zero_padding/reclassificado_em_outros/reclassificado_em_irmao/divergencia_nao_explicada
    para linhas só num dos filings; layer=5 text_stability: ambiguo, fila de revisão da similaridade;
    cd_conta NULL = resumo do par; detalhe é JSON — use json_extract).
    cd_conta_ds_timeline: trilha de cada linha (pai + nome) entre filings consecutivos — renumerado/reformulacao/ambiguo/
    nova/removida com cd_conta_anterior (estavel não é gravada).
    demonstrativos_trimestrais: valor de cada trimestre da DRE/DFC_MI/DVA por conta e safra ('original' = colunas
    Último, 'reapresentado' = Penúltimo do exercício seguinte); use vl_final e origem; 4T = DFP − acum 3T; flag
    reapresentacao_intra_ano quando publicado ≠ derivado (layer=6 em consistency_flags);
    reclassificacao_entre_filings quando os dois filings da subtração estão em layouts diferentes para a linha.
    Sempre identifique empresas pelo CNPJ (SELECT cnpj FROM companies WHERE ticker = ?).
    Limites: 500 linhas, 30.000 caracteres por resposta, 20 s por consulta e 25.000 caracteres por célula — texto maior volta cortado com
    o marcador "…[truncado: N chars]" (texto_extraido passa de 12 milhões de caracteres). Para textos longos
    leia em pedaços com substr(texto_extraido, inicio, tamanho), ou use o FTS:
    SELECT snippet(ipe_docs_fts, -1, '[', ']', '…', 40) FROM ipe_docs_fts WHERE ipe_docs_fts MATCH '...'.
    """
    s = sql.strip().rstrip(";")
    if not re.match(r"^(SELECT|WITH)\b", s, re.I) or _FORBIDDEN.search(_LITERAIS.sub(" ", s)):
        raise ValueError("Apenas SELECT (ou WITH ... SELECT) é permitido.")
    conn = get_db()
    conn.set_authorizer(_authorizer)
    prazo = _com_prazo(conn)
    try:
        try:
            cur = conn.execute(s)
            rows = cur.fetchmany(MAX_ROWS + 1)
        except sqlite3.DatabaseError as e:
            if time.monotonic() > prazo:
                raise ValueError(
                    f"Consulta abortada após {QUERY_TIMEOUT_S:g} s. Restrinja por cnpj_companhia/data, "
                    "use LIMIT, ou busque texto pelo FTS (ipe_docs_fts MATCH) em vez de LIKE '%...%'."
                ) from None
            if "not authorized" in str(e) or "authorization denied" in str(e):
                raise ValueError(f"Operação não permitida (somente leitura): {e}") from None
            raise
        colunas = [d[0] for d in cur.description]
        linhas = [[_cortar(v) for v in r] for r in rows[:MAX_ROWS]]
        aviso = f"resultado truncado em {MAX_ROWS} linhas — use LIMIT/filtros" if len(rows) > MAX_ROWS else None
        return _tabular(colunas, linhas, aviso)
    finally:
        conn.close()


@mcp.tool()
def resolve_company(texto: str) -> dict:
    """Acha a empresa pelo ticker (PETR4, ou só a raiz PETR), nome parcial (acento e caixa não importam) ou CNPJ.
    Devolve até 5 candidatos {cnpj, ticker, nome_cvm, setor}; use o CNPJ nas demais consultas.
    Se não achar, diz que a empresa não está na base (ver o onboarding da skill) em vez de devolver vazio.
    ON, PN e UNIT são a mesma empresa: a base guarda um ticker por CNPJ."""
    t = (texto or "").strip()
    if not t:
        raise ValueError("Informe um ticker, nome ou CNPJ.")
    conn = get_db()
    try:
        _com_prazo(conn)
        digitos = re.sub(r"\D", "", t)
        cands = []

        def busca(where: str, args: tuple):
            for r in conn.execute(
                    f"SELECT cnpj, ticker, nome_cvm, setor FROM companies WHERE {where} LIMIT 6", args):
                d = dict(r)
                if d not in cands:
                    cands.append(d)

        if len(digitos) >= 8 and re.fullmatch(r"[\d./-]+", t):
            busca("replace(replace(replace(cnpj,'.',''),'/',''),'-','') LIKE ?", (digitos + "%",))
        up = t.upper()
        if not cands and re.fullmatch(r"[A-Z]{4}\d{1,2}", up):
            busca("ticker = ?", (up,))
            if not cands:   # ITUB3 → ITUB4: um ticker por empresa
                busca("substr(ticker,1,4) = ?", (up[:4],))
        if not cands and re.fullmatch(r"[A-Z]{4}", up):
            busca("substr(ticker,1,4) = ?", (up,))
        if not cands:
            # LIKE do SQLite só ignora caixa em ASCII: compara em Python, sem acento
            alvo = _sem_acento(t)
            for r in conn.execute("SELECT cnpj, ticker, nome_cvm, setor FROM companies"):
                if alvo in _sem_acento(r["nome_cvm"] or "") or alvo == _sem_acento(r["ticker"] or ""):
                    cands.append(dict(r))
        if not cands:
            return {"candidatos": [], "aviso": f"'{t}' não está na base (companies). Se for pergunta sobre os últimos "
                    "dias, consulte o RAD; senão ofereça o onboarding (references/manutencao.md), sem disparar a carga."}
        out = {"candidatos": cands[:5]}
        if len(cands) > 1:
            out["aviso"] = "mais de uma empresa: confirme com o usuário ou declare a premissa"
        return out
    finally:
        conn.close()


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


@mcp.tool()
def list_tables() -> dict:
    """Lista tabelas e views do banco. `rows` é a contagem de linhas das tabelas; nas views vem null
    (contar uma view executa a consulta inteira, o que levava minutos)."""
    conn = get_db()
    try:
        _com_prazo(conn)
        names = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE '%_fts_%' ORDER BY type, name"
        ).fetchall()
        out = []
        for name, typ in names:
            n = None
            if typ == "table":
                try:
                    n = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                except sqlite3.Error:   # inclui o prazo estourado: a tabela fica sem contagem
                    pass
            out.append([name, typ, n])
        return _tabular(["name", "type", "rows"], out)
    finally:
        conn.close()


@mcp.tool()
def describe_table(table: str) -> dict:
    """Retorna as colunas (nome, tipo, not null, pk) de uma tabela ou view."""
    if not _IDENT.match(table):
        raise ValueError("Nome de tabela inválido.")
    conn = get_db()
    try:
        _com_prazo(conn)
        cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        if not cols:
            raise ValueError(f"Tabela '{table}' não existe.")
        return _tabular(["cid", "name", "type", "notnull", "dflt_value", "pk"], [list(c) for c in cols])
    finally:
        conn.close()


# ---------- Entry ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--http", action="store_true", help="usa transporte streamable-http em vez de stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERRO: banco não encontrado em {DB_PATH}", file=sys.stderr)
        print("Rode: bash setup.sh  (e os ingestores em scripts/ingest/)", file=sys.stderr)
        sys.exit(1)

    if args.http:
        mcp.settings.host, mcp.settings.port = args.host, args.port
        print(f"CVM MCP Server em http://{args.host}:{args.port}/mcp — banco: {DB_PATH}", file=sys.stderr)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio


if __name__ == "__main__":
    main()
