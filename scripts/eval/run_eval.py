#!/usr/bin/env python3
"""
Executor da Etapa 2: roda o conjunto golden numa sessão nova do Claude Code (com o CLAUDE.md
do projeto e só o MCP cvm-research) e grava um relatório comparável entre execuções.

    .venv/bin/python scripts/eval/run_eval.py --rotulo baseline
    .venv/bin/python scripts/eval/run_eval.py --ids q001,q015 --rotulo teste
    .venv/bin/python scripts/eval/run_eval.py --comparar a.json b.json

Correção:
  - numero / contagem / numero_par: automática. O prompt pede uma última linha `RESPOSTA: ...`
    e o valor é comparado com a tolerância do golden (contagem aceita original ou com reapresentações).
  - documento / fato / sem_dado: um segundo `claude -p` (sem ferramentas) julga contra a resposta
    de referência e o critério escrito na armadilha.

O relatório vai para docs/proximos-passos/avaliacao/runs/<data>_<rotulo>.json.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
GOLDEN = RAIZ / "docs/proximos-passos/avaliacao/golden_v0.json"
RUNS = RAIZ / "docs/proximos-passos/avaliacao/runs"
AUTOMATICOS = {"numero", "contagem", "numero_par"}

SUFIXO = {
    "numero": "\n\nTermine a resposta com uma última linha exatamente neste formato: `RESPOSTA: <número em R$, sem separador de milhar, ponto decimal>`.",
    "contagem": "\n\nTermine a resposta com uma última linha exatamente neste formato: `RESPOSTA: <inteiro>`.",
    "numero_par": "\n\nTermine a resposta com uma última linha exatamente neste formato: `RESPOSTA: original=<número em R$>; reapresentado=<número em R$>` (sem separador de milhar, ponto decimal).",
}


def config_mcp(db: str | None) -> str:
    env = {"CVM_DB_PATH": db} if db else {}
    cfg = {"mcpServers": {"cvm-research": {
        "command": str(RAIZ / ".venv/bin/python"),
        "args": [str(RAIZ / "scripts/mcp/cvm_mcp.py")],
        "env": env}}}
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(cfg, f)
    f.close()
    return f.name


def claude(prompt: str, mcp: str | None, modelo: str | None, timeout: int) -> list[dict]:
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--permission-mode", "dontAsk"]
    if mcp:
        cmd += ["--strict-mcp-config", "--mcp-config", mcp,
                "--allowedTools", "mcp__cvm-research__query", "mcp__cvm-research__list_tables",
                "mcp__cvm-research__describe_table"]
    else:
        cmd += ["--tools", ""]
    if modelo:
        cmd += ["--model", modelo]
    p = subprocess.run(cmd, cwd=RAIZ if mcp else tempfile.gettempdir(), capture_output=True,
                       text=True, timeout=timeout)
    eventos = []
    for linha in p.stdout.splitlines():
        try:
            eventos.append(json.loads(linha))
        except json.JSONDecodeError:
            pass
    return eventos


def resumir(eventos: list[dict]) -> dict:
    chamadas, erros_sql, abortadas, resposta = 0, 0, 0, ""
    r = {}
    for e in eventos:
        msg = e.get("message") or {}
        conteudo = msg.get("content") if isinstance(msg.get("content"), list) else []
        for c in conteudo:
            if e.get("type") == "assistant" and c.get("type") == "tool_use":
                chamadas += 1
            if e.get("type") == "user" and c.get("type") == "tool_result" and c.get("is_error"):
                txt = json.dumps(c.get("content"), ensure_ascii=False).lower()
                erros_sql += 1
                if "20 s" in txt or "timeout" in txt or "interrupt" in txt or "abort" in txt:
                    abortadas += 1
        if e.get("type") == "result":
            r = e
            resposta = e.get("result") or ""
    u = r.get("usage") or {}
    return {
        "resposta": resposta,
        "chamadas_ferramenta": chamadas,
        "erros_ferramenta": erros_sql,
        "consultas_abortadas": abortadas,
        "turnos": r.get("num_turns"),
        "tokens_entrada": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                          + (u.get("cache_creation_input_tokens") or 0),
        "tokens_saida": u.get("output_tokens"),
        "custo_usd": r.get("total_cost_usd"),
        "duracao_s": round((r.get("duration_ms") or 0) / 1000, 1),
        "erro_sessao": bool(r.get("is_error")) or not r,
    }


def numeros(txt: str) -> list[float]:
    out = []
    for m in re.findall(r"-?\d[\d.]*(?:[.,]\d+)?", txt):
        try:
            out.append(float(m))
        except ValueError:
            pass
    return out


def perto(x: float, ref: float, tol: float) -> bool:
    return abs(x - ref) <= tol * abs(ref) if ref else abs(x) <= tol


def linha_resposta(txt: str) -> str | None:
    m = re.findall(r"RESPOSTA:\s*(.+)", txt)
    return m[-1].strip().strip("`") if m else None


def corrigir_auto(q: dict, resposta: str) -> tuple[bool, str]:
    linha = linha_resposta(resposta)
    if linha is None:
        return False, "sem linha RESPOSTA"
    tol = q.get("tolerancia_rel") or 0
    ref = q["resposta"]
    if q["tipo"] == "numero_par":
        got = dict(re.findall(r"(original|reapresentado)\s*=\s*(-?[\d.]+)", linha))
        ok = all(k in got and perto(float(got[k]), ref[k], 0.005) for k in ("original", "reapresentado"))
        return ok, linha
    vals = numeros(linha.replace(",", ""))
    ok = bool(vals) and perto(vals[0], float(ref), tol)
    if not ok and q["tipo"] == "contagem" and vals and 0 < ref - vals[0] <= 3 \
            and re.search(r"reapresent|reenvi|duplic|mesma vers|duas vezes|idêntic", resposta, re.I):
        # a referência conta reapresentações; contar só os originais também vale (ver 02-avaliacao.md)
        return True, f"{linha} (sem reapresentações; referência {ref})"
    return ok, linha


def corrigir_juiz(q: dict, resposta: str, modelo: str | None) -> tuple[bool, str]:
    prompt = (
        "Você é um corretor. Julgue se a RESPOSTA do assistente está correta em relação à REFERÊNCIA.\n"
        f"PERGUNTA: {q['pergunta']}\nREFERÊNCIA: {json.dumps(q['resposta'], ensure_ascii=False)}\n"
        f"CRITÉRIO (armadilha testada): {q['armadilha']}\nRESPOSTA: {resposta}\n\n"
        "Seja estrito com datas, nomes e percentuais (arredondamento de 1 casa é aceito). "
        "Para 'sem_dado', exige informar até quando vai a base e/ou apontar o RAD, sem afirmar que não houve evento. "
        'Responda só com JSON: {"correto": true|false, "motivo": "..."}'
    )
    ev = claude(prompt, None, modelo, 180)
    txt = resumir(ev)["resposta"]
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        j = json.loads(m.group(0))
        return bool(j["correto"]), j.get("motivo", "")
    except Exception:
        return False, f"juiz ilegível: {txt[:120]}"


def rodar_uma(q: dict, mcp: str, modelo: str | None, juiz: str | None, timeout: int) -> dict:
    prompt = q["pergunta"] + SUFIXO.get(q["tipo"], "")
    t0 = time.time()
    try:
        res = resumir(claude(prompt, mcp, modelo, timeout))
    except subprocess.TimeoutExpired:
        res = {"resposta": "", "erro_sessao": True, "duracao_s": round(time.time() - t0, 1)}
    if res["erro_sessao"] and not res["resposta"]:
        ok, nota = False, "sessão falhou ou estourou o tempo"
    elif q["tipo"] in AUTOMATICOS:
        ok, nota = corrigir_auto(q, res["resposta"])
    else:
        ok, nota = corrigir_juiz(q, res["resposta"], juiz)
    return {"id": q["id"], "tipo": q["tipo"], "correto": ok, "nota_correcao": nota, **res}


def relatorio(resultados: list[dict]) -> dict:
    def agg(rs):
        n = len(rs) or 1
        soma = lambda k: sum((r.get(k) or 0) for r in rs)
        return {"n": len(rs), "acerto": round(sum(r["correto"] for r in rs) / n, 3),
                "chamadas_por_pergunta": round(soma("chamadas_ferramenta") / n, 2),
                "tokens_por_pergunta": round((soma("tokens_entrada") + soma("tokens_saida")) / n),
                "erros_ferramenta": soma("erros_ferramenta"),
                "consultas_abortadas": soma("consultas_abortadas"),
                "duracao_media_s": round(soma("duracao_s") / n, 1),
                "custo_usd": round(soma("custo_usd"), 3)}
    tipos = sorted({r["tipo"] for r in resultados})
    return {"geral": agg(resultados), "por_tipo": {t: agg([r for r in resultados if r["tipo"] == t]) for t in tipos}}


def comparar(a: str, b: str) -> None:
    ra, rb = (json.load(open(x)) for x in (a, b))
    print(f"{'':14}{'A':>10}{'B':>10}")
    for k in ra["resumo"]["geral"]:
        print(f"{k:24}{ra['resumo']['geral'][k]:>10}{rb['resumo']['geral'][k]:>10}")
    da = {r["id"]: r["correto"] for r in ra["resultados"]}
    for r in rb["resultados"]:
        if r["id"] in da and da[r["id"]] != r["correto"]:
            print(f"{r['id']}: {'acertou' if da[r['id']] else 'errou'} -> {'acertou' if r['correto'] else 'errou'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotulo", default="run")
    ap.add_argument("--ids", help="lista separada por vírgula")
    ap.add_argument("--modelo")
    ap.add_argument("--juiz", help="modelo do corretor (padrão: o mesmo da sessão)")
    ap.add_argument("--db", help="banco a consultar (CVM_DB_PATH)")
    ap.add_argument("--paralelo", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--comparar", nargs=2, metavar=("A", "B"))
    a = ap.parse_args()
    if a.comparar:
        return comparar(*a.comparar)

    g = json.load(open(GOLDEN))
    qs = g["perguntas"]
    if a.ids:
        qs = [q for q in qs if q["id"] in a.ids.split(",")]
    mcp = config_mcp(a.db)
    t0 = time.time()
    with ThreadPoolExecutor(a.paralelo) as ex:
        res = list(ex.map(lambda q: rodar_uma(q, mcp, a.modelo, a.juiz or a.modelo, a.timeout), qs))
    for r in res:
        print(f"{r['id']} {r['tipo']:11} {'OK ' if r['correto'] else 'ERRO'} {r.get('chamadas_ferramenta')} chamadas  {r['nota_correcao'][:70]}")
    out = {"rotulo": a.rotulo, "executado_em": date.today().isoformat(), "golden_gerado_em": g["gerado_em"],
           "modelo": a.modelo, "duracao_total_s": round(time.time() - t0),
           "resumo": relatorio(res), "resultados": res}
    RUNS.mkdir(parents=True, exist_ok=True)
    dest = RUNS / f"{date.today().isoformat()}_{a.rotulo}.json"
    json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out["resumo"]["geral"], ensure_ascii=False))
    print(f"relatório: {dest.relative_to(RAIZ)}")


if __name__ == "__main__":
    sys.exit(main())
