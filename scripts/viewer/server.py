"""Visualizador local das demonstrações como reportadas (DFP/ITR) e da série trimestral.

Uso: .venv/bin/python scripts/viewer/server.py [--port 8765]
Somente leitura: abre o SQLite com mode=ro e serve index.html + uma API JSON.

Cada linha da tabela é uma LINHA ECONÔMICA, não um cd_conta. A empresa renumera as
contas que cria entre filings — na DFC da Multiplan o código 6.03.08 é "Dividendos"
no 1T e "Pagamento de encargos sobre debêntures" no 2T — então montar a série
horizontal por código mistura contas diferentes numa linha só. O encadeamento usa
check_text_stability.match_filings, a mesma escada da Camada 5 que a Camada 6 usa
para derivar os trimestres, e por isso o visualizador depende da .venv (pandas).

Nas visões ITR e DFP, a linha vem pronta da tabela `linha_empresa` (Etapa 6): o mesmo
encadeamento que o MCP e o LLM usam, feito sobre ITR e DFP juntos em ordem de data, com o
reatamento depois de buraco e as decisões humanas de `linha_decisao`. Empresa sem linhas na
tabela (banco anterior à Etapa 6 ou ainda não reconstruído) cai no encadeamento na hora.
Na série trimestral, dentro de um exercício o vínculo vem pronto do banco
(demonstrativos_trimestrais.cd_conta_b, gravado pela Camada 6); só na virada de ano o
casamento é calculado aqui. Par de similaridade ambígua não encadeia: a série quebra em
duas, que é o mesmo critério conservador do banco.
"""
import argparse
import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
from consistency_utils import normalize_text  # noqa: E402

DB = ROOT / "cvm_research.db"
HTML = Path(__file__).with_name("index.html")
TIPOS = {"DRE", "BPA", "BPP", "DFC_MI", "DVA"}
FONTES = {"ITR", "DFP", "TRI"}
FLUXO = {"DRE", "DFC_MI", "DVA"}


def conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def natkey(cd):
    return [int(p) if p.isdigit() else 0 for p in cd.split(".")]


def companies():
    with conn() as c:
        rows = c.execute(
            "SELECT cnpj, ticker, nome_cvm, setor FROM companies ORDER BY ticker"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Encadeamento ─────────────────────────────────────────────────────────────

# Fonte única do encadeamento (Etapa 6): o mesmo código grava `linha_empresa` e alimenta a tela.
from linha_economica import encadear  # noqa: E402,F401


def montar(series, colunas, valores, extras=None):
    """Transforma as séries em linhas da tabela. valores[i][cd] = valor na coluna i;
    extras[nome][i][cd] = campo extra por célula (origem, flag). A linha é rotulada
    pelo código e pelo nome da coluna mais recente em que ela aparece."""
    n = len(colunas)
    extras = extras or {}
    out = []
    for s in series:
        if not s:
            continue
        ult = max(s)
        cds = [s.get(i) for i in range(n)]
        nomes = [colunas[i][cd][0] for i, cd in enumerate(cds) if cd is not None]
        linha = {
            "cd": s[ult],
            "cds": cds,
            "ds": colunas[ult][s[ult]][0],
            "fixa": colunas[ult][s[ult]][1],
            "nomes": len({x for x in nomes if x}),
            "v": [valores[i].get(cd) if cd is not None else None for i, cd in enumerate(cds)],
        }
        for nome, tabela in extras.items():
            linha[nome] = [tabela[i].get(cd) if cd is not None else None for i, cd in enumerate(cds)]
        if any(v is not None for v in linha["v"]):
            out.append(linha)
    out.sort(key=lambda r: natkey(r["cd"]))
    return out


def series_da_tabela(cnpj, fonte, tipo, datas, linhas):
    """Séries {coluna: cd} agrupando as células pelo linha_id de `linha_empresa`, ou None se a tabela não tem a
    empresa (aí o chamador encadeia na hora). Célula sem linha_id, ou com o linha_id já ocupado naquela coluna,
    vira uma linha própria: na dúvida, duas linhas em vez de uma série inventada."""
    with conn() as c:
        try:
            ids = {(r[0], r[1]): r[2] for r in c.execute(
                f"""SELECT data_referencia, cd_conta, linha_id FROM linha_empresa
                    WHERE cnpj_companhia = ? AND tipo_doc = ? AND fonte = ?
                      AND data_referencia IN ({','.join('?' * len(datas))})""",
                (cnpj, tipo, fonte, *datas))}
        except sqlite3.OperationalError:   # banco sem a tabela
            return None
    if not ids:
        return None
    por_id, soltas = {}, []
    for i, d in enumerate(datas):
        for cd in sorted(linhas[i], key=natkey):
            lid = ids.get((d, cd))
            if lid is None or i in por_id.get(lid, {}):
                soltas.append({i: cd})
            else:
                por_id.setdefault(lid, {})[i] = cd
    return list(por_id.values()) + soltas


# ── Visões ───────────────────────────────────────────────────────────────────

def statement(cnpj, fonte, tipo, modo, n):
    """Matriz linha econômica × filing, colunas 'Último' da versão mais recente de cada filing."""
    with conn() as c:
        rows = c.execute(
            """SELECT data_referencia, versao, dt_ini_exerc, dt_fim_exerc,
                      cd_conta, ds_conta, vl_conta, st_conta_fixa
               FROM demonstrativos_contabeis
               WHERE cnpj_companhia = ? AND fonte = ? AND tipo_doc = ?
                 AND ordem_exercicio = 'Último'""",
            (cnpj, fonte, tipo),
        ).fetchall()

    ultima = {}
    for r in rows:
        d = r["data_referencia"]
        ultima[d] = max(ultima.get(d, 0), r["versao"])
    datas = sorted(ultima, reverse=True)[:n][::-1]  # n mais recentes, ordem cronológica
    if not datas:
        return {"columns": [], "rows": []}

    # por filing, escolhe o período: trimestre isolado (maior dt_ini) ou acumulado (menor)
    ini = {}
    for r in rows:
        d = r["data_referencia"]
        if d in ultima and r["versao"] == ultima[d] and r["dt_ini_exerc"]:
            ini.setdefault(d, set()).add(r["dt_ini_exerc"])
    escolha = {d: (max(v) if modo == "iso" else min(v)) for d, v in ini.items()}

    idx = {d: i for i, d in enumerate(datas)}
    linhas = [{} for _ in datas]
    valores = [{} for _ in datas]
    fim = {}
    for r in rows:
        d = r["data_referencia"]
        if d not in idx or r["versao"] != ultima[d]:
            continue
        if d in escolha and r["dt_ini_exerc"] != escolha[d]:
            continue
        fim[d] = r["dt_fim_exerc"]
        i = idx[d]
        linhas[i].setdefault(r["cd_conta"], (r["ds_conta"], r["st_conta_fixa"]))
        valores[i].setdefault(r["cd_conta"], r["vl_conta"])

    series = series_da_tabela(cnpj, fonte, tipo, datas, linhas)
    out = montar(series if series is not None else encadear(linhas), linhas, valores)
    cols = [
        {"data": d, "versao": ultima[d], "ini": escolha.get(d), "fim": fim.get(d), "tri": None}
        for d in datas
    ]
    return {"columns": cols, "rows": out, "tri": False, "encadeamento": "tabela" if series is not None else "calculado"}


def serie_trimestral(cnpj, tipo, safra, n):
    """Série trimestral com 4T. Fluxos vêm da Camada 6; BPA/BPP juntam ITR e DFP (saldo)."""
    if tipo not in FLUXO:
        return _saldos_trimestrais(cnpj, tipo, n)

    with conn() as c:
        rows = c.execute(
            """SELECT exercicio_ini, dt_ini_exerc, dt_fim_exerc, trimestre, cd_conta, ds_conta,
                      cd_conta_b, casamento, vl_final, origem, flag
               FROM demonstrativos_trimestrais
               WHERE cnpj_companhia = ? AND tipo_doc = ? AND safra = ?""",
            (cnpj, tipo, safra),
        ).fetchall()
        fixas = dict(
            c.execute(
                """SELECT cd_conta, MAX(st_conta_fixa) FROM demonstrativos_contabeis
                   WHERE cnpj_companhia = ? AND tipo_doc = ? AND fonte = 'DFP' GROUP BY cd_conta""",
                (cnpj, tipo),
            ).fetchall()
        )
    chaves = sorted({(r["dt_fim_exerc"], r["exercicio_ini"], r["trimestre"], r["dt_ini_exerc"])
                     for r in rows})[-n:]
    if not chaves:
        return {"columns": [], "rows": [], "tri": True}
    idx = {(k[1], k[2]): i for i, k in enumerate(chaves)}

    linhas = [{} for _ in chaves]
    valores = [{} for _ in chaves]
    origens = [{} for _ in chaves]
    flags = [{} for _ in chaves]
    ligacoes = {}
    for r in rows:
        i = idx.get((r["exercicio_ini"], r["trimestre"]))
        if i is None:
            continue
        cd = r["cd_conta"]
        linhas[i].setdefault(cd, (r["ds_conta"], fixas.get(cd)))
        valores[i][cd] = r["vl_final"]
        origens[i][cd] = r["origem"]
        flags[i][cd] = r["flag"] or None
        # O vínculo gravado pela Camada 6 só vale quando a coluna anterior é mesmo o
        # trimestre anterior do mesmo exercício; na virada de ano o casamento é calculado.
        if r["cd_conta_b"] and r["casamento"] != "ambiguo" and i > 0:
            ant = chaves[i - 1]
            if ant[1] == r["exercicio_ini"] and ant[2] == r["trimestre"] - 1:
                ligacoes.setdefault(i, {})[cd] = r["cd_conta_b"]

    out = montar(encadear(linhas, ligacoes), linhas, valores,
                 {"o": origens, "f": flags})
    cols = [{"data": k[0], "ini": k[3], "fim": k[0], "versao": None, "tri": k[2]} for k in chaves]
    return {"columns": cols, "rows": out, "tri": True}


def _saldos_trimestrais(cnpj, tipo, n):
    """BPA/BPP: posição na data, não fluxo. Junta os ITRs e os DFPs e encadeia igual."""
    a = statement(cnpj, "ITR", tipo, "iso", 80)
    b = statement(cnpj, "DFP", tipo, "iso", 80)
    cols = sorted(a["columns"] + b["columns"], key=lambda c: c["data"])[-n:]
    if not cols:
        return {"columns": [], "rows": [], "tri": False}
    pos = {c["data"]: i for i, c in enumerate(cols)}
    linhas = [{} for _ in cols]
    valores = [{} for _ in cols]
    for src in (a, b):
        for r in src["rows"]:
            for j, col in enumerate(src["columns"]):
                i = pos.get(col["data"])
                cd = r["cds"][j]
                if i is None or cd is None:
                    continue
                linhas[i].setdefault(cd, (r["ds"], r["fixa"]))
                valores[i][cd] = r["v"][j]
    out = montar(encadear(linhas), linhas, valores)
    for c in cols:
        c["tri"] = None
    return {"columns": cols, "rows": out, "tri": False}


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/companies":
                self._json(companies())
            elif u.path == "/api/statement":
                fonte, tipo = q.get("fonte", "ITR"), q.get("tipo", "DRE")
                if fonte not in FONTES or tipo not in TIPOS or "cnpj" not in q:
                    return self._json({"error": "parâmetros inválidos"}, 400)
                modo = q.get("modo", "iso")
                n = max(1, min(int(q.get("n", 12)), 80))
                if fonte == "TRI":
                    safra = q.get("safra", "original")
                    if safra not in ("original", "reapresentado"):
                        return self._json({"error": "safra inválida"}, 400)
                    return self._json(serie_trimestral(q["cnpj"], tipo, safra, n))
                self._json(statement(q["cnpj"], fonte, tipo, modo, n))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # demo local: devolve o erro ao navegador
            self._json({"error": str(e)}, 500)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if not DB.exists():
        sys.exit(f"banco não encontrado em {DB} — rode `bash bootstrap.sh` antes")
    print(f"http://127.0.0.1:{a.port}  (db: {DB})")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
