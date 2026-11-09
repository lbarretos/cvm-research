"""Métrica de qualidade do texto extraído por página e por documento (Etapa 9, item 9.7).

Identifica defeitos comuns de extração em PDFs da CVM:
- Fontes Identity-H sem ToUnicode / glifos perdidos: "(cid:N)"
- Tabelas ou textos rotacionados / espaçados: tokens de uma só letra ("re n d a e c o n trib u iç ã o")
- Caracteres fora do padrão português/latino: caracteres de controle ou mojibake não mapeado

Classificação por página/bloco:
- 'ruim': cid > 5% OU letras soltas > 30% (mín. 20 tokens) OU caracteres estranhos > 10%
- 'parcial': cid > 1% OU letras soltas > 20% (mín. 20 tokens) OU caracteres estranhos > 4%
- 'ok': caso contrário

Classificação resumida do documento:
- 'ruim': > 15% das páginas ruins OU > 10 páginas ruins OU doc pequeno (<= 5 págs) com >= 2 ruins
- 'parcial': pelo menos 1 página ruim OU páginas parciais > 3% do total
- 'ok': restante
"""
import json
import re

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

    if cid_pct > 0.05 or (n_toks >= 20 and soltas_pct > 0.30) or estranhos_pct > 0.10:
        status = "ruim"
    elif cid_pct > 0.01 or (n_toks >= 20 and soltas_pct > 0.20) or estranhos_pct > 0.04:
        status = "parcial"
    else:
        status = "ok"

    return {
        "chars": n_chars,
        "cid_pct": round(cid_pct, 4),
        "soltas_pct": round(soltas_pct, 4),
        "estranhos_pct": round(estranhos_pct, 4),
        "status": status,
    }


def avaliar_documento(texto: str | None) -> tuple[str, str]:
    """Avalia um documento inteiro página a página (se houver \\f) ou em blocos.
    
    Retorna (qualidade_resumida, json_texto_qualidade).
    qualidade_resumida: 'ok' | 'parcial' | 'ruim'
    """
    if not texto:
        return "ruim", json.dumps({"motivo": "sem_texto"})

    tem_ff = "\x0c" in texto
    if tem_ff:
        partes = texto.split("\x0c")
    else:
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
    elif n_ruins > 0 or n_parciais > max(1, int(total_paginas * 0.03)):
        doc_status = "parcial"
    else:
        doc_status = "ok"

    info = {
        "total_paginas": total_paginas,
        "tem_quebra_pagina": tem_ff,
        "n_ruins": n_ruins,
        "n_parciais": n_parciais,
        "piores": sorted(piores, key=lambda x: (x["status"] == "ruim", x["cid_pct"] + x["soltas_pct"]), reverse=True)[:5],
    }

    return doc_status, json.dumps(info, ensure_ascii=False)


def pagina_esta_degradada(texto_qualidade_json: str | None, pagina: int | None, doc_qualidade: str | None) -> bool:
    """Verifica se uma página específica (ou o documento) está com qualidade ruim."""
    if doc_qualidade == "ruim":
        return True
    if not texto_qualidade_json or pagina is None:
        return False
    try:
        data = json.loads(texto_qualidade_json)
        piores = data.get("piores", [])
        for p in piores:
            if p.get("pagina") == pagina and p.get("status") == "ruim":
                return True
    except Exception:
        pass
    return False
