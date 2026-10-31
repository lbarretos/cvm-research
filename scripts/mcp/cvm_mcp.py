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
    search_docs(consulta…) → busca por trecho (FR, CM, AVI, RCA, assembleias, press-release), deduplicada
    read_doc(protocolo…)   → lê um documento por trechos, a partir de uma posição
    get_financials(ticker, conceitos…) → fatos padronizados (D&A, capex, dividendos, juros, dívida…) com a checagem
    resolve_bond(texto)    → código (RUMOB6, CRA024004SB), ISIN, CNPJ ou nome de emissor/devedor → títulos de renda fixa
    get_bond(codigo)       → ficha do título: emissão, partes, garantias, lastro, taxas ANBIMA, grupo econômico, documentos
    search_bonds(…)        → filtra títulos por tipo, indexador, vencimento, emissor/devedor ou grupo
    search_bond_docs(…)    → busca no texto das escrituras/termos de securitização; read_bond_doc lê por posição
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


def _tabular(colunas: list[str], linhas: list[list], aviso: str | None = None,
             limite: int | None = None) -> dict:
    """{colunas, linhas} em vez de um dict por linha (o nome de cada coluna não se repete).
    Corta as linhas finais até caber em `limite` (MAX_RESPONSE_CHARS, ou a fatia de uma seção) e diz
    quantas ficaram de fora."""
    limite = limite or MAX_RESPONSE_CHARS
    total = len(linhas)
    usados = len(json.dumps(colunas, ensure_ascii=False))
    mantidas = []
    for l in linhas:
        n = len(json.dumps(l, ensure_ascii=False, default=str))
        if mantidas and usados + n > limite:
            break
        # uma única linha maior que o orçamento: as células já foram cortadas em MAX_CELL_CHARS;
        # corta de novo para o resultado não estourar o contexto
        if not mantidas and n > limite:
            l = [_cortar_para(v, max(200, limite // max(len(l), 1))) for v in l]
            n = len(json.dumps(l, ensure_ascii=False, default=str))
        mantidas.append(l)
        usados += n
    out = {"colunas": colunas, "linhas": mantidas}
    avisos = [aviso] if aviso else []
    if len(mantidas) < total:
        avisos.append(f"resposta cortada em {len(mantidas)} de {total} linhas para caber em "
                      f"{limite} caracteres: restrinja colunas/filtros ou use LIMIT")
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


_FTS_OPERADORES = re.compile(r'["()]|\b(AND|OR|NOT|NEAR)\b|\w:')


def _consulta_fts(consulta: str) -> str:
    """Texto livre vira AND de termos (prefixo com * é mantido); sintaxe FTS5 explícita passa direto."""
    c = consulta.strip()
    if _FTS_OPERADORES.search(c):
        return c
    termos = re.findall(r"\w+\*?", c)
    return " AND ".join(f'"{t[:-1]}"*' if t.endswith("*") else f'"{t}"' for t in termos)


@mcp.tool()
def search_docs(consulta: str, ticker: str | None = None, categorias: list[str] | None = None,
                desde: str | None = None, ate: str | None = None, k: int = 10,
                versoes_antigas: bool = False) -> dict:
    """Busca por trecho (~2 mil caracteres) nos documentos da camada quente do IPE: Fato Relevante, Comunicado ao
    Mercado, Aviso aos Acionistas, Reunião da Administração, Assembleia (ata, proposta, sumário, edital) e
    press-release. Devolve os k melhores trechos (BM25), sem repetir texto idêntico, só de versões vigentes
    (versoes_antigas=True inclui as substituídas), com o protocolo para ler em volta com read_doc.
    consulta: termos (AND implícito; acento e caixa não importam; `dividend*` para prefixo) ou sintaxe FTS5
    ("frase exata", OR, NEAR(a b, 10)). ticker: filtra a empresa (ticker, nome ou CNPJ). categorias: lista de
    ipe_docs.categoria. desde/ate: data_entrega 'YYYY-MM-DD'.
    Não cobre DFs completas, prospectos nem relatórios de agente fiduciário (camada fria): para esses use o FTS
    por documento (ipe_docs_fts) via query. Se o último dado é recente, lembre da defasagem do IPE (ver a skill)."""
    q = _consulta_fts(consulta)
    if not q:
        raise ValueError("Consulta vazia.")
    k = max(1, min(int(k), 30))
    conn = get_db()
    try:
        prazo = _com_prazo(conn)
        match = f"texto : ({q})"
        aviso = None
        if ticker:
            r = resolve_company(ticker)
            if not r["candidatos"]:
                return {"colunas": [], "linhas": [], "aviso": r["aviso"]}
            if len(r["candidatos"]) > 1:
                return {"colunas": [], "linhas": [], "aviso": "ticker ambíguo: "
                        + "; ".join(f"{c['ticker']} {c['nome_cvm']}" for c in r["candidatos"])}
            match += f' AND cnpj_tok : "{re.sub(r"\D", "", r["candidatos"][0]["cnpj"])}"'
        where, args = ["ipe_chunks_fts MATCH ?"], [match]
        if not versoes_antigas:
            where.append("c.is_latest = 1")
        if categorias:
            where.append(f"c.categoria IN ({','.join('?' * len(categorias))})")
            args += categorias
        if desde:
            where.append("c.data_entrega >= ?")
            args.append(desde)
        if ate:
            where.append("c.data_entrega <= ?")
            args.append(ate)
        sql = ("SELECT c.hash, c.rep_protocolo, c.rep_ordem, c.data_entrega, c.categoria, c.tipo, c.assunto, "
               "snippet(ipe_chunks_fts, 0, '[', ']', ' … ', 48), i.link_download "
               "FROM ipe_chunks_fts JOIN ipe_chunks c ON c.chunk_id = ipe_chunks_fts.rowid "
               "LEFT JOIN ipe_docs i ON i.protocolo_entrega = c.rep_protocolo "
               f"WHERE {' AND '.join(where)} ORDER BY ipe_chunks_fts.rank LIMIT ?")
        try:
            rows = conn.execute(sql, args + [k * 5]).fetchall()
        except sqlite3.OperationalError as e:
            if time.monotonic() > prazo:
                raise ValueError("Busca abortada por tempo: restrinja por ticker, categorias ou datas.") from None
            if "no such table" in str(e):
                raise ValueError("Índice de trechos ausente: rode a migração 2026-10-06_ipe_chunks.sql e "
                                 "scripts/ingest/build_chunks.py.") from None
            raise ValueError(f"Consulta FTS inválida ({e}). Use termos simples ou aspas.") from None
        vistos, linhas = set(), []
        for h, proto, ordem, data, cat, tipo, assunto, trecho, link in rows:
            # mesmo hash = texto idêntico; mesmo trecho destacado = boilerplate repetido entre documentos
            chave = (h, re.sub(r"\W+", "", trecho.lower()))
            if h in vistos or chave[1] in vistos:
                continue
            vistos.update(chave)
            linhas.append([proto, ordem, data, cat, tipo, assunto, trecho, link])
            if len(linhas) == k:
                break
        if not linhas:
            aviso = ("nenhum trecho; a busca cobre só a camada quente e versões vigentes. Tente menos termos, "
                     "prefixo (termo*) ou versoes_antigas=True")
        return _tabular(["protocolo", "ordem", "data_entrega", "categoria", "tipo", "assunto", "trecho", "link"],
                        linhas, aviso)
    finally:
        conn.close()


@mcp.tool()
def read_doc(protocolo: str, ordem: int = 0, offset: int = 0, max_chars: int = 20_000) -> dict:
    """Lê um documento a partir de um trecho. Use o `protocolo` e a `ordem` devolvidos por search_docs: o texto
    vem limpo (hifenização e cabeçalhos tratados), do trecho `ordem` em diante, até max_chars (máx. 28.000).
    A resposta traz `proximo_ordem` para continuar e `total_trechos`. Documentos fora da camada quente não têm
    trechos: nesse caso o texto bruto vem por posição (`offset` em caracteres)."""
    max_chars = max(500, min(int(max_chars), 28_000))
    conn = get_db()
    try:
        _com_prazo(conn)
        doc = conn.execute("SELECT categoria, tipo, assunto, data_entrega, link_download, chars_extraidos "
                           "FROM ipe_docs WHERE protocolo_entrega = ?", (protocolo,)).fetchone()
        if doc is None:
            raise ValueError(f"Protocolo '{protocolo}' não existe em ipe_docs.")
        meta = {"protocolo": protocolo, "categoria": doc[0], "tipo": doc[1], "assunto": doc[2],
                "data_entrega": doc[3], "link": doc[4]}
        chunks = conn.execute(
            "SELECT d.ordem, c.texto FROM ipe_chunk_docs d JOIN ipe_chunks c USING (chunk_id) "
            "WHERE d.protocolo_entrega = ? AND d.ordem >= ? ORDER BY d.ordem", (protocolo, max(0, ordem))).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM ipe_chunk_docs WHERE protocolo_entrega = ?", (protocolo,)).fetchone()[0]
        if total:
            texto, ultimo = "", None
            for o, t in chunks:
                novo = _sem_sobreposicao(texto, t)
                if texto and len(texto) + len(novo) > max_chars:
                    break
                texto += novo
                ultimo = o
            prox = ultimo + 1 if ultimo is not None and ultimo + 1 < total else None
            return {**meta, "texto": texto[:max_chars], "ordem_inicio": chunks[0][0] if chunks else None,
                    "ordem_fim": ultimo, "total_trechos": total, "proximo_ordem": prox}
        (txt,) = conn.execute("SELECT substr(texto_extraido, ?, ?) FROM ipe_docs WHERE protocolo_entrega = ?",
                              (max(0, offset) + 1, max_chars, protocolo)).fetchone() or (None,)
        if not txt:
            return {**meta, "texto": None, "aviso": "sem texto extraído (ver link) ou offset além do fim"}
        fim = max(0, offset) + len(txt)
        return {**meta, "texto": txt, "offset": offset, "chars_total": doc[5], "proximo_offset": fim,
                "aviso": "documento fora da camada quente: texto bruto, sem limpeza, por posição"}
    finally:
        conn.close()


def _sem_sobreposicao(anterior: str, t: str) -> str:
    """Junta trechos consecutivos tirando a sobreposição de até 250 caracteres entre eles."""
    if not anterior:
        return t
    for n in range(min(250, len(anterior), len(t)), 20, -1):
        if anterior.endswith(t[:n]):
            return t[n:]
    return "\n" + t


@mcp.tool()
def get_financials(ticker: str, conceitos: list[str] | None = None, fonte: str = "DFP",
                   desde: str | None = None, ate: str | None = None,
                   incluir_nao_publicados: bool = False) -> dict:
    """Fatos padronizados de uma empresa (tabela fato_padronizado, Etapa 7): conceitos comparáveis entre empresas
    mesmo quando a DFC usa nomes e códigos próprios. Uma linha por (período, conceito) com o valor em R$, quantas
    linhas da demonstração foram somadas (`n_linhas`), como foi obtido (`metodo`: S = conta fixa da CVM, regra,
    derivado), `confianca` e a `checagem` (ok; ok_<definição alternativa da DVA>; sem_gabarito; divergente...).
    Só plano padrão (bancos e seguradoras não têm esses conceitos). Conceitos DFC: da_total, da_ex_ppa,
    da_direito_uso, da_ppa, capex_total, capex_imob, capex_intang, capex_conjunto, dividendos_pagos, juros_pagos,
    capt_divida, amort_divida, divida_liquida_fluxo, arrend_pago, recompra, ir_pago; de contas fixas: receita_liquida,
    resultado_bruto, ebit, lucro_liquido, cfo, cfi, cff, variacao_caixa, caixa_final, ativo_total, patrimonio_liquido;
    da DMPL (coluna PL consolidado): dividendos_declarados (5.04.06 + 5.04.07 + contas próprias de dividendo/JCP),
    aumento_capital (5.04.01, sem capitalização de reservas), recompra_dmpl (5.04.04, confere a recompra da DFC).
    Sem `conceitos`, devolve todos. fonte: DFP (anual) ou ITR (acumulado do ano). Fatos que falharam na checagem só
    vêm com incluir_nao_publicados=True. Ausência de um conceito num período significa que a empresa não tem linha
    dele naquela DFC (ou o sinal não bateu), não que o valor seja zero. Mostre sempre `metodo` e `checagem`."""
    conn = get_db()
    try:
        _com_prazo(conn)
        r = resolve_company(ticker)
        if not r["candidatos"]:
            return {"colunas": [], "linhas": [], "aviso": r["aviso"]}
        if len(r["candidatos"]) > 1:
            return {"colunas": [], "linhas": [], "aviso": "ticker ambíguo: "
                    + "; ".join(f"{c['ticker']} {c['nome_cvm']}" for c in r["candidatos"])}
        where, args = ["cnpj_companhia = ?", "fonte = ?"], [r["candidatos"][0]["cnpj"], fonte]
        if conceitos:
            where.append(f"conceito IN ({','.join('?' * len(conceitos))})")
            args += conceitos
        if desde:
            where.append("data_referencia >= ?")
            args.append(desde)
        if ate:
            where.append("data_referencia <= ?")
            args.append(ate)
        if not incluir_nao_publicados:
            where.append("publicado = 1")
        try:
            rows = conn.execute(
                "SELECT data_referencia, periodo_ini, periodo_fim, conceito, valor, n_linhas, metodo, confianca, "
                f"checagem, publicado FROM fato_padronizado WHERE {' AND '.join(where)} "
                "ORDER BY data_referencia DESC, conceito", args).fetchall()
        except sqlite3.OperationalError:
            raise ValueError("Tabela fato_padronizado ausente: rode a migração 2026-10-16_taxonomia.sql e "
                             "scripts/analysis/taxonomia.py --full.") from None
        aviso = None if rows else "nenhum fato (empresa fora do plano padrão, conceito inexistente ou filtros)"
        return _tabular(["data_referencia", "periodo_ini", "periodo_fim", "conceito", "valor", "n_linhas", "metodo",
                         "confianca", "checagem", "publicado"], [list(x) for x in rows], aviso)
    finally:
        conn.close()


# ---------- Renda fixa (Etapa 8) ----------

_RF_AUSENTE = ("Tabelas de renda fixa ausentes: rode a migração 2026-10-30_renda_fixa.sql e os ingestores "
               "ingest_rf_cadastro.py / ingest_rf_taxas.py (ver references/renda-fixa.md da skill).")
_ATIVO_COLS = ["codigo", "tipo", "isin", "emissor_cnpj", "emissor_nome", "devedor_cnpj", "devedor_nome", "emissao",
               "serie", "data_emissao", "data_vencimento", "valor_emissao", "indexador", "remuneracao",
               "especie_garantia", "incentivada_12431", "agente_fiduciario", "situacao", "fonte", "taxa_data",
               "taxa_indicativa", "pu", "pct_pu_par", "duration_du"]


def _rf(conn, sql: str, args=()) -> list[list]:
    try:
        return [list(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            raise ValueError(_RF_AUSENTE) from None
        raise


def _rf_busca(conn, texto: str) -> list[str]:
    """Códigos que casam com o texto: código exato, ISIN, CNPJ (emissor, devedor ou parte) ou nome."""
    t = texto.strip()
    up = t.upper()
    cods = [r[0] for r in _rf(conn, "SELECT codigo FROM rf_ativos WHERE codigo = ? OR isin = ?", (up, up))]
    if cods:
        return cods
    if _rf(conn, "SELECT 1 FROM rf_taxas WHERE codigo = ? LIMIT 1", (up,)):
        return [up]   # a ANBIMA precifica, mas o cadastro ainda não tem o título
    digitos = re.sub(r"\D", "", t)
    if len(digitos) >= 8 and re.fullmatch(r"[\d./-]+", t):
        dig = "replace(replace(replace({c},'.',''),'/',''),'-','') LIKE ?"
        return [r[0] for r in _rf(conn, f"""
            SELECT codigo FROM rf_ativos WHERE {dig.format(c='emissor_cnpj')} OR {dig.format(c='devedor_cnpj')}
            UNION SELECT codigo FROM rf_partes WHERE {dig.format(c='cnpj')}""", (digitos + "%",) * 3)]
    alvo = _sem_acento(t)
    return [r[0] for r in _rf(conn, "SELECT codigo, emissor_nome, devedor_nome FROM rf_ativos")
            if alvo in _sem_acento(r[1] or "") or alvo in _sem_acento(r[2] or "")]


@mcp.tool()
def resolve_bond(texto: str) -> dict:
    """Acha títulos de renda fixa (debêntures, CRI, CRA) pelo código de negociação (RUMOB6, CRA024004SB), ISIN,
    CNPJ (do emissor, da securitizadora, do devedor ou de um garantidor) ou parte do nome do emissor/devedor.
    Devolve até 50 títulos com tipo, emissor, devedor, vencimento, remuneração e a última taxa indicativa ANBIMA.
    Use o `codigo` em get_bond."""
    if not (texto or "").strip():
        raise ValueError("Informe um código, ISIN, CNPJ ou nome.")
    conn = get_db()
    try:
        _com_prazo(conn)
        cods = _rf_busca(conn, texto)
        if not cods:
            return {"colunas": [], "linhas": [], "aviso": f"'{texto}' não está em rf_ativos nem em rf_taxas. "
                    "Confira o código no site da ANBIMA/B3; se for título novo, rode ingest_rf_cadastro.py."}
        cols = ["codigo", "tipo", "emissor_nome", "devedor_nome", "data_vencimento", "remuneracao", "taxa_data",
                "taxa_indicativa"]
        ph = ",".join("?" * len(cods[:200]))
        linhas = _rf(conn, f"SELECT {','.join(cols)} FROM vw_rf_ativo WHERE codigo IN ({ph}) "
                           "ORDER BY data_vencimento DESC LIMIT 50", cods[:200])
        achados = {l[0] for l in linhas}
        linhas += [[c, None, None, None, None, None, None, None] for c in cods if c not in achados][:5]
        aviso = None
        if len(cods) > 50:
            aviso = f"{len(cods)} títulos; mostrando 50 (use search_bonds para filtrar)"
        if any(l[1] is None for l in linhas):
            aviso = "; ".join(filter(None, [aviso, "título só nas taxas ANBIMA, sem cadastro (rode ingest_rf_cadastro.py)"]))
        return _tabular(cols, linhas, aviso)
    finally:
        conn.close()


def _rf_cnpjs_partes(conn, codigo: str) -> list[list]:
    """(papel, cnpj, nome) das partes com CNPJ: cadastro do título + rf_partes (exceto agente fiduciário)."""
    return _rf(conn, """
        SELECT CASE WHEN tipo IN ('CRI','CRA') THEN 'securitizadora' ELSE 'emissor' END, emissor_cnpj, emissor_nome
          FROM rf_ativos WHERE codigo = ? AND emissor_cnpj IS NOT NULL
        UNION SELECT 'devedor', devedor_cnpj, devedor_nome FROM rf_ativos WHERE codigo = ? AND devedor_cnpj IS NOT NULL
        UNION SELECT papel, cnpj, nome FROM rf_partes
          WHERE codigo = ? AND cnpj IS NOT NULL AND papel <> 'agente_fiduciario'""", (codigo,) * 3)


@mcp.tool()
def get_bond(codigo: str, dias_taxa: int = 30) -> dict:
    """Ficha de um título de renda fixa (debênture, CRI, CRA) pelo código (RUMOB6, ERDVB4, CRA024004SB…).
    Seções, cada uma {colunas, linhas}:
    - emissao: cadastro (SND para debêntures; oferta CVM para CRI/CRA) + última taxa indicativa.
    - ofertas: registro(s) da oferta na CVM (rito, data, valor, líder); na Resolução 160 (2023+), também a descrição
      oficial das garantias, do lastro e dos devedores/coobrigados e a agência de rating contratada.
    - partes: emissor/securitizadora, devedor, fiadores, garantidores, cedentes, agente fiduciário. `fonte` 'cadastro'
      = campo publicado (confianca 1); 'pdf' = extraída por regra do documento, 'cvm_oferta' = extraída por regra da
      descrição da oferta na CVM, as duas com o trecho em `evidencia`.
    - garantias e lastro: extraídos dos PDFs (tipo, prestador, evidência). `escopo` diz de quem é a garantia: 'titulo'
      (do próprio CRI/CRA/debênture) ou 'lastro' (do instrumento que paga o CRI/CRA, ex.: aval na CPR-F). Vazio NÃO quer
      dizer sem garantia: o PDF pode não ter sido ingerido (o aviso diz). `especie_garantia` da emissão é o campo do SND.
    - taxas: taxa indicativa ANBIMA, PU, % PU par e duration dos últimos `dias_taxa` dias (preço de referência, não negócio).
    - grupo: cadeia de controle de cada parte com FRE na base (nível 1 = controlador direto), atravessando holdings.
    - ativos_do_grupo: outros títulos cujas partes têm o mesmo controlador (ou são o próprio controlador).
    - documentos: escrituras/termos lidos (doc_id para search_bond_docs/read_bond_doc).
    Cite sempre a fonte e, para dado de PDF, a evidência."""
    cod = (codigo or "").strip().upper()
    conn = get_db()
    try:
        _com_prazo(conn)
        cands = _rf_busca(conn, cod)
        if not cands:
            return {"aviso": f"'{cod}' não encontrado (rf_ativos/rf_taxas). Use resolve_bond."}
        if cod not in cands:
            if len(cands) > 1:
                return {"aviso": f"'{cod}' não é um código; candidatos: {', '.join(cands[:20])}"}
            cod = cands[0]   # ISIN → código
        q = MAX_RESPONSE_CHARS // 10
        out, avisos = {}, []
        emis = _rf(conn, f"SELECT {','.join(_ATIVO_COLS)} FROM vw_rf_ativo WHERE codigo = ?", (cod,))
        out["emissao"] = _tabular(_ATIVO_COLS, emis, limite=q)
        if not emis:
            avisos.append("título sem cadastro (só taxa ANBIMA): rode ingest_rf_cadastro.py")
        a = dict(zip(_ATIVO_COLS, emis[0])) if emis else {}
        # a CVM não publica o código: casa por emissor + emissão (+ série no 400/476), como ingest_rf_cadastro.py
        cols = ["fonte", "numero_registro", "tipo_ativo", "emissao", "serie", "data_registro", "valor_total",
                "remuneracao", "rito", "publico_alvo", "lider_nome", "agente_fiduciario", "avaliador_risco",
                "tipo_lastro", "descricao_garantias", "descricao_lastro", "devedores_coobrigados"]
        out["ofertas"] = _tabular(cols, _rf(conn, f"""
            SELECT {','.join(cols[:-3])}, substr(descricao_garantias, 1, 1500), substr(descricao_lastro, 1, 800),
                   substr(devedores_coobrigados, 1, 800)
            FROM rf_ofertas
            WHERE emissor_cnpj = :emissor AND CAST(emissao AS INTEGER) = CAST(:emissao AS INTEGER)
              AND (serie IS NULL OR :serie IS NULL OR CAST(serie AS INTEGER) = CAST(:serie AS INTEGER))
            ORDER BY data_registro LIMIT 10""",
            {"emissor": a.get("emissor_cnpj"), "emissao": a.get("emissao"), "serie": a.get("serie")}), limite=3 * q)
        cols = ["papel", "cnpj", "nome", "fonte", "confianca", "doc_id", "evidencia"]
        out["partes"] = _tabular(cols, _rf(conn, """
            SELECT papel, cnpj, nome, fonte, confianca, doc_id, substr(evidencia, 1, 300) FROM rf_partes
            WHERE codigo = ? ORDER BY fonte <> 'cadastro', papel""", (cod,)), limite=2 * q)
        cols = ["tipo", "escopo", "prestador_nome", "prestador_cnpj", "descricao", "fonte", "confianca", "doc_id",
                "evidencia"]
        out["garantias"] = _tabular(cols, _rf(conn, f"""
            SELECT tipo, escopo, prestador_nome, prestador_cnpj, descricao, fonte, confianca, doc_id,
                   substr(evidencia, 1, 400)
            FROM rf_garantias WHERE codigo = ? ORDER BY escopo DESC, tipo""", (cod,)), limite=2 * q)
        cols = ["tipo_lastro", "devedor_nome", "devedor_cnpj", "fonte", "confianca", "doc_id", "evidencia"]
        out["lastro"] = _tabular(cols, _rf(conn, """
            SELECT tipo_lastro, devedor_nome, devedor_cnpj, fonte, confianca, doc_id, substr(evidencia, 1, 300)
            FROM rf_lastro WHERE codigo = ?""", (cod,)), limite=q)
        cols = ["data", "indice", "taxa_indicativa", "taxa_compra", "taxa_venda", "pu", "pct_pu_par", "duration_du",
                "referencia"]
        out["taxas"] = _tabular(cols, _rf(conn, f"SELECT {','.join(cols)} FROM rf_taxas WHERE codigo = ? "
                                               "ORDER BY data DESC LIMIT ?", (cod, max(1, min(int(dias_taxa), 60)))),
                                limite=q)
        # a securitizadora emite CRI/CRA de devedores sem relação entre si: não define grupo econômico
        partes = [p for p in _rf_cnpjs_partes(conn, cod) if p[0] != "securitizadora"]
        cnpjs = sorted({p[1] for p in partes})
        ph = ",".join("?" * len(cnpjs)) or "NULL"
        cols = ["cnpj_origem", "nivel", "controlador_nome", "controlador_doc", "tipo_pessoa", "percentual", "via_cnpj",
                "via_data_fre"]
        grupo = _rf(conn, f"SELECT {','.join(cols)} FROM rf_grupo WHERE cnpj_origem IN ({ph}) "
                          "ORDER BY cnpj_origem, nivel", cnpjs)
        out["grupo"] = _tabular(cols, grupo, limite=q)
        cols = ["codigo", "tipo", "papel", "cnpj", "nome", "data_vencimento", "remuneracao", "taxa_indicativa"]
        out["ativos_do_grupo"] = _tabular(cols, _rf(conn, f"""
            WITH ctrl AS (SELECT controlador_doc AS doc FROM rf_grupo WHERE cnpj_origem IN ({ph})
                          UNION SELECT value FROM json_each(?)),
                 membros AS (SELECT cnpj_origem AS cnpj FROM rf_grupo WHERE controlador_doc IN (SELECT doc FROM ctrl)
                             UNION SELECT doc FROM ctrl),
                 partes AS (SELECT codigo, CASE WHEN tipo IN ('CRI','CRA') THEN 'securitizadora' ELSE 'emissor' END
                                   AS papel, emissor_cnpj AS cnpj, emissor_nome AS nome FROM rf_ativos
                            UNION SELECT codigo, 'devedor', devedor_cnpj, devedor_nome FROM rf_ativos
                            UNION SELECT codigo, papel, cnpj, nome FROM rf_partes WHERE papel <> 'agente_fiduciario')
            SELECT p.codigo, v.tipo, p.papel, p.cnpj, MAX(p.nome), v.data_vencimento, v.remuneracao, v.taxa_indicativa
            FROM partes p JOIN vw_rf_ativo v ON v.codigo = p.codigo
            WHERE p.cnpj IN (SELECT cnpj FROM membros) AND p.codigo <> ? AND p.papel <> 'securitizadora'
            GROUP BY p.codigo, p.papel, p.cnpj
            ORDER BY v.data_vencimento DESC LIMIT 100""", (*cnpjs, json.dumps(cnpjs), cod)), limite=q)
        cols = ["doc_id", "origem", "data_entrega", "tipo", "assunto", "chars_extraidos", "extracao_falhou", "link_download"]
        docs = _rf(conn, f"""SELECT {','.join('d.' + c for c in cols)} FROM rf_docs d
                             JOIN rf_doc_ativo x ON x.doc_id = d.doc_id WHERE x.codigo = ?
                             ORDER BY d.data_entrega DESC""", (cod,))
        out["documentos"] = _tabular(cols, docs, limite=q)
        if not any(d[5] for d in docs):
            origem = ("da descrição da oferta na CVM e do cadastro" if out["garantias"]["linhas"] or out["lastro"]["linhas"]
                      else "só do cadastro")
            avisos.append(f"nenhum PDF lido para {cod}: garantias, lastro e garantidores vêm {origem}. Para ler a "
                          f"escritura/termo: python scripts/ingest/ingest_rf_docs.py --codigo {cod}")
        if partes and not grupo:
            avisos.append("nenhuma parte tem FRE na base (empresa fora do watchlist ou fechada): grupo não calculado")
        if not out["taxas"]["linhas"]:
            avisos.append("sem taxa ANBIMA na janela (título não precificado ou ingest_rf_taxas.py não rodou)")
        if avisos:
            out["aviso"] = "; ".join(avisos)
        return out
    finally:
        conn.close()


@mcp.tool()
def search_bonds(texto: str | None = None, tipo: str | None = None, indexador: str | None = None,
                 vence_de: str | None = None, vence_ate: str | None = None, incentivada: bool | None = None,
                 grupo_de: str | None = None, so_com_taxa: bool = False, limite: int = 100) -> dict:
    """Filtra títulos de renda fixa. texto: nome/CNPJ do emissor ou devedor (como resolve_bond). tipo: DEB, CRI ou CRA.
    indexador: DI, IPCA, IGP-M, PRE. vence_de/vence_ate: 'YYYY-MM-DD'. incentivada: Lei 12.431. grupo_de: CNPJ de um
    controlador (ou de uma empresa: usa os controladores dela em rf_grupo) e devolve os títulos de todo o grupo.
    so_com_taxa: só os precificados pela ANBIMA. Até 300 linhas, ordenadas por vencimento."""
    conn = get_db()
    try:
        _com_prazo(conn)
        where, args = [], []
        if texto:
            cods = _rf_busca(conn, texto)
            if not cods:
                return {"colunas": [], "linhas": [], "aviso": f"nada casa com '{texto}'"}
            where.append(f"codigo IN ({','.join('?' * len(cods))})")
            args += cods
        if tipo:
            where.append("tipo = ?")
            args.append(tipo.upper())
        if indexador:
            where.append("indexador = ?")
            args.append(indexador.upper())
        if vence_de:
            where.append("data_vencimento >= ?")
            args.append(vence_de)
        if vence_ate:
            where.append("data_vencimento <= ?")
            args.append(vence_ate)
        if incentivada is not None:
            where.append("incentivada_12431 = ?")
            args.append(1 if incentivada else 0)
        if so_com_taxa:
            where.append("taxa_indicativa IS NOT NULL")
        if grupo_de:
            r = _rf(conn, "SELECT controlador_doc FROM rf_grupo WHERE replace(replace(replace(cnpj_origem,'.',''),'/',''),'-','') = ?",
                    (re.sub(r"\D", "", grupo_de),))
            docs = [x[0] for x in r] or [grupo_de]
            membros = [x[0] for x in _rf(conn, f"SELECT cnpj_origem FROM rf_grupo WHERE controlador_doc IN "
                                               f"({','.join('?' * len(docs))})", docs)]
            todos = sorted(set(membros) | set(docs) | {grupo_de})
            ph = ",".join("?" * len(todos))
            where.append(f"(emissor_cnpj IN ({ph}) OR devedor_cnpj IN ({ph}) OR codigo IN "
                         f"(SELECT codigo FROM rf_partes WHERE cnpj IN ({ph}) AND papel <> 'agente_fiduciario'))")
            args += todos * 3
        cols = ["codigo", "tipo", "emissor_nome", "devedor_nome", "data_vencimento", "indexador", "remuneracao",
                "especie_garantia", "incentivada_12431", "valor_emissao", "taxa_data", "taxa_indicativa", "duration_du"]
        linhas = _rf(conn, f"SELECT {','.join(cols)} FROM vw_rf_ativo "
                           f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY data_vencimento LIMIT ?",
                     (*args, max(1, min(int(limite), 300))))
        return _tabular(cols, linhas, None if linhas else "nenhum título com esses filtros")
    finally:
        conn.close()


@mcp.tool()
def search_bond_docs(consulta: str, codigo: str | None = None, k: int = 10) -> dict:
    """Busca no texto das escrituras, aditamentos e termos de securitização ingeridos (rf_docs_fts). consulta: termos
    (AND implícito) ou sintaxe FTS5 ("cessão fiduciária", NEAR(fiança controladora, 10)). codigo: restringe ao título.
    Devolve doc_id, os títulos ligados e o trecho; leia em volta com read_bond_doc."""
    q = _consulta_fts(consulta)
    if not q:
        raise ValueError("Consulta vazia.")
    conn = get_db()
    try:
        _com_prazo(conn)
        where, args = ["rf_docs_fts MATCH ?"], [f"texto_extraido : ({q})"]
        if codigo:
            where.append("d.doc_id IN (SELECT doc_id FROM rf_doc_ativo WHERE codigo = ?)")
            args.append(codigo.strip().upper())
        try:
            linhas = _rf(conn, f"""
                SELECT d.doc_id, (SELECT group_concat(codigo, ' ') FROM rf_doc_ativo x WHERE x.doc_id = d.doc_id),
                       d.data_entrega, d.tipo, snippet(rf_docs_fts, 2, '[', ']', ' … ', 48)
                FROM rf_docs_fts JOIN rf_docs d ON d.rowid = rf_docs_fts.rowid
                WHERE {' AND '.join(where)} ORDER BY rf_docs_fts.rank LIMIT ?""",
                (*args, max(1, min(int(k), 30))))
        except sqlite3.OperationalError as e:
            raise ValueError(f"Consulta FTS inválida ({e}). Use termos simples ou aspas.") from None
        return _tabular(["doc_id", "codigos", "data_entrega", "tipo", "trecho"], linhas,
                        None if linhas else "nenhum trecho (o PDF do título foi ingerido? ver get_bond.documentos)")
    finally:
        conn.close()


@mcp.tool()
def read_bond_doc(doc_id: str, offset: int = 0, max_chars: int = 20_000) -> dict:
    """Lê o texto de um documento de renda fixa (rf_docs) a partir de `offset` (caracteres), até max_chars (máx. 28.000).
    Para achar o ponto, use search_bond_docs e procure o trecho; `proximo_offset` continua a leitura."""
    max_chars = max(500, min(int(max_chars), 28_000))
    conn = get_db()
    try:
        _com_prazo(conn)
        r = _rf(conn, "SELECT tipo, assunto, data_entrega, link_download, chars_extraidos, "
                      "substr(texto_extraido, ?, ?) FROM rf_docs WHERE doc_id = ?",
                (max(0, offset) + 1, max_chars, doc_id))
        if not r:
            raise ValueError(f"doc_id '{doc_id}' não existe em rf_docs.")
        tipo, assunto, data, link, total, txt = r[0]
        out = {"doc_id": doc_id, "tipo": tipo, "assunto": assunto, "data_entrega": data, "link": link,
               "chars_total": total, "offset": offset, "texto": txt}
        if txt:
            fim = max(0, offset) + len(txt)
            out["proximo_offset"] = fim if total and fim < total else None
        else:
            out["aviso"] = "sem texto extraído (ver link) ou offset além do fim"
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
