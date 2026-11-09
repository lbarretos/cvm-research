"""Stress test da Etapa 9, Bloco B (item 9.7): calibração da métrica de qualidade de texto por página.

Avalia 300 DFs sorteados + casos conhecidos (TUPY3 2025, LEVE3, MYPK3) para calibrar
os limiares de ok/parcial/ruim e medir a taxa de falso positivo.

Uso: .venv/bin/python docs/proximos-passos/stress/st9_qualidade.py "$PWD/cvm_research.db"
"""
import json
import re
import sqlite3
import sys
import time

_RE_TOK = re.compile(r"\S+")
_LATIN_OK = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " \t\n\r\x0c"
    ".,;:!?-/\\()[]{}'\"`~@#$%&*+=_<>|§°ºª€£±—–…«»“”‘’"
    "áéíóúâêîôûãõàèìòùäëïöüçÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÄËÏÖÜÇ"
)


def avaliar_pagina(texto: str) -> dict:
    """Calcula métricas de qualidade para uma página (ou trecho) de texto."""
    n_chars = len(texto)
    if n_chars == 0:
        return {"chars": 0, "cid_pct": 0.0, "soltas_pct": 0.0, "estranhos_pct": 0.0, "status": "ok"}

    cid_count = texto.count("(cid:")
    cid_pct = (cid_count * 7) / n_chars

    toks = _RE_TOK.findall(texto)
    n_toks = len(toks)
    if n_toks > 0:
        soltas = sum(1 for t in toks if len(t) == 1 and t.isalpha())
        soltas_pct = soltas / n_toks
    else:
        soltas_pct = 0.0

    estranhos = sum(1 for ch in texto if ch not in _LATIN_OK)
    estranhos_pct = estranhos / n_chars

    # Classificação da página:
    # - ruim: cid > 5% OU letras soltas > 30% (com pelo menos 20 tokens) OU estranhos > 10%
    # - parcial: cid > 1% OU letras soltas > 20% OU estranhos > 4%
    # - ok: caso contrário
    status = "ok"
    if cid_pct > 0.05 or (n_toks >= 20 and soltas_pct > 0.30) or estranhos_pct > 0.10:
        status = "ruim"
    elif cid_pct > 0.01 or (n_toks >= 20 and soltas_pct > 0.20) or estranhos_pct > 0.04:
        status = "parcial"

    return {
        "chars": n_chars,
        "cid_pct": round(cid_pct, 4),
        "soltas_pct": round(soltas_pct, 4),
        "estranhos_pct": round(estranhos_pct, 4),
        "status": status,
    }


def avaliar_documento(texto: str | None) -> tuple[str, str]:
    """Avalia um documento inteiro página a página (se houver \f) ou em blocos.
    
    Retorna (qualidade_resumida, json_texto_qualidade).
    qualidade_resumida: 'ok' | 'parcial' | 'ruim'
    """
    if not texto:
        return "ruim", json.dumps({"motivo": "sem_texto"})

    # Se tiver \f, avalia página a página
    tem_ff = "\x0c" in texto
    if tem_ff:
        partes = texto.split("\x0c")
    else:
        # Documento sem \f: divide em blocos de ~2000 chars em quebras de linha
        linhas = texto.split("\n")
        partes, bloco = [], []
        cur_len = 0
        for l in linhas:
            bloco.append(l)
            cur_len += len(l) + 1
            if cur_len >= 2000:
                partes.append("\n".join(bloco))
                bloco, cur_len = [], 0
        if bloco:
            partes.append("\n".join(bloco))

    total_paginas = len(partes)
    piores = []
    n_ruins = 0
    n_parciais = 0

    for i, p_txt in enumerate(partes, 1):
        if not p_txt.strip():
            continue
        res = avaliar_pagina(p_txt)
        if res["status"] == "ruim":
            n_ruins += 1
            piores.append({"pagina": i, **res})
        elif res["status"] == "parcial":
            n_parciais += 1
            if len(piores) < 10:
                piores.append({"pagina": i, **res})

    pct_ruim = n_ruins / max(total_paginas, 1)

    if pct_ruim > 0.15 or (total_paginas <= 5 and n_ruins >= 2) or (n_ruins > 10):
        doc_status = "ruim"
    elif n_ruins > 0 or n_parciais > 0:
        doc_status = "parcial"
    else:
        doc_status = "ok"

    info = {
        "total_paginas": total_paginas,
        "tem_quebra_pagina": tem_ff,
        "n_ruins": n_ruins,
        "n_parciais": n_parciais,
        "piores": sorted(piores, key=lambda x: (x["status"] == "ruim", x["cid_pct"] + x["soltas_pct"]), reverse=True)[:5]
    }

    return doc_status, json.dumps(info, ensure_ascii=False)


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "cvm_research.db"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    t0 = time.time()

    print("Carregando casos conhecidos...")
    casos = [
        ("TUPY3 DFP 2025", "006343IPE311220250114408280-21"),
        ("MYPK3 3T23", "011932IPE300920230104523812-04"),
        ("LEVE3 DFP 2021", "008575IPE311220210104463411-44"),
        ("WEGE3 DFP 2025", "005410IPE311220250113110255-78"),
    ]

    for label, proto in casos:
        row = conn.execute("SELECT texto_extraido FROM ipe_docs WHERE protocolo_entrega = ?", (proto,)).fetchone()
        if row and row[0]:
            status, info_json = avaliar_documento(row[0])
            info = json.loads(info_json)
            print(f"[{status.upper()}] {label} ({proto}): {info['total_paginas']} págs, {info['n_ruins']} ruins, {info['n_parciais']} parciais")
            if info["piores"]:
                print(f"    Pior: pág {info['piores'][0].get('pagina')} -> {info['piores'][0]}")
        else:
            print(f"[NÃO ENCONTRADO] {label} ({proto})")

    print("\nAvaliando amostra de 300 DFs...")
    sample = conn.execute("""
        SELECT protocolo_entrega, cnpj_companhia, tipo, data_referencia, texto_extraido
        FROM ipe_docs
        WHERE categoria = 'Dados Econômico-Financeiros'
          AND tipo LIKE 'Demonstrações Financeiras%'
          AND texto_extraido IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 300
    """).fetchall()

    contagem = {"ok": 0, "parcial": 0, "ruim": 0}
    t_amostra = time.time()
    for proto, cnpj, tipo, dref, txt in sample:
        st, _ = avaliar_documento(txt)
        contagem[st] += 1

    dur = time.time() - t_amostra
    print(f"Resultado na amostra de {len(sample)} DFs em {dur:.1f}s:")
    for k, v in contagem.items():
        print(f"  {k}: {v} ({v/len(sample)*100:.1f}%)")

    conn.close()
    print(f"\nConcluído em {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
