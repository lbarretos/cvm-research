"""
Extração por regra das partes, garantias e lastro de um título a partir do texto dos documentos (rf_docs).

Determinística e sem chamada a modelo: lê o que a escritura ou o termo de securitização escreve de
forma padronizada.
- Partes: cada CNPJ do texto, com o nome que vem antes ("RUMO S.A., sociedade por ações…") e o termo
  definido que vem depois (“Emissora”, “Fiadora”, “Devedora”, “Agente Fiduciário”…), que dá o papel.
  CNPJ sem termo definido reconhecível não vira parte.
- Garantias: vocabulário (alienação/cessão fiduciária, fiança, aval, hipoteca, penhor, fundo de reserva,
  subordinação, coobrigação, garantia flutuante, quirografária), descartando menção negada ("não contará
  com fiança"). Uma linha por tipo e documento, com o primeiro trecho como evidência.
- Lastro (CRI/CRA): instrumentos citados perto de "lastro" ou "direitos creditórios".

Tudo vai com `evidencia` e `confianca` < 1 (fonte 'pdf'). A precisão não foi medida contra revisão humana:
quem responde deve citar o trecho. Nunca apaga nem altera o que veio do cadastro.

Uso:
  python extrai_rf.py                 # documentos com texto ainda não lidos
  python extrai_rf.py --codigo RUMOB6 # refaz os documentos do título
  python extrai_rf.py --todos         # refaz tudo
"""
import argparse
import re
from datetime import datetime, timezone

import rf_fontes as F
from utils import get_db, upsert

CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}\s*/\s*\d{4}\s*-\s*\d{2}")
# (“Emissora”) · ("Fiadora") · (doravante denominada “Devedora”) · (em conjunto, os “Fiadores”)
TERMO_RE = re.compile(r"\(\s*(?:[^()“”\"]{0,80}?)?[“\"']\s*([^”\"']{3,60}?)\s*[”\"']")
# o nome da parte termina na vírgula que abre a qualificação ("RUMO S.A., sociedade por ações…")
QUALIF_RE = re.compile(r",\s*(?:sociedade|companhia|institui|pessoa|empresa|fundo|com sede|inscrit|com registro)",
                       re.I)
# e começa depois do último separador: ';', ':', aspas, vírgula ou enumeração "(ii)" / "b)"
SEPARADOR_RE = re.compile(r"[;:”\"“,]|\(\s*[ivxlc]+\s*\)|\b[a-h]\)")

# termo definido (normalizado) → papel; a ordem importa ("agente fiduciário" antes de qualquer outro)
PAPEIS = [
    (r"agente fiduci", "agente_fiduciario"),
    (r"securitizador", "securitizadora"),
    (r"\bemissora\b|\bcompanhia\b|\bemitente\b", "emissor"),
    (r"devedor", "devedor"),
    (r"fiador", "fiador"),
    (r"avalista", "avalista"),
    (r"garantidor|interveniente garant", "garantidor"),
    (r"cedente", "cedente"),
    (r"coobrig", "coobrigado"),
]

GARANTIAS = [
    ("alienacao_fiduciaria", r"aliena[çc][ãa]o fiduci[áa]ria"),
    ("cessao_fiduciaria",    r"cess[ãa]o fiduci[áa]ria"),
    ("fianca",               r"\bfian[çc]a\b"),
    ("aval",                 r"\baval\b"),
    ("hipoteca",             r"\bhipoteca"),
    ("penhor",               r"\bpenhor\b"),
    ("fundo_reserva",        r"fundo de reserva"),
    ("subordinacao",         r"\bs[ée]ries? subordinadas?\b|\bsubordina[çc][ãa]o\b"),
    ("coobrigacao",          r"\bcoobriga[çc][ãa]o\b"),
    ("garantia_flutuante",   r"garantia flutuante"),
    ("quirografaria",        r"quirograf[áa]ri"),
    ("sem_garantia",         r"(?:n[ãa]o contar[ãa]o?|n[ãa]o ser[ãa]o?) (?:com )?(?:qualquer |nenhuma )?garantia"),
]
NEGACAO = re.compile(r"\b(n[ãa]o|sem|nenhuma|inexist\w*|exceto)\b[^.;]{0,40}$")

LASTRO = [
    ("CPR-F",          r"\bCPR[- ]?F\b|c[ée]dulas? de produto rural financeira"),
    ("CPR",            r"c[ée]dulas? de produto rural(?! financeira)"),
    ("CDCA",           r"\bCDCAs?\b|certificados? de direitos credit[óo]rios do agroneg[óo]cio"),
    ("CCB",            r"\bCCBs?\b|c[ée]dulas? de cr[ée]dito banc[áa]rio"),
    ("CCI",            r"\bCCIs?\b|c[ée]dulas? de cr[ée]dito imobili[áa]rio"),
    ("nota_comercial", r"notas? comercia(?:l|is)"),
    ("NCE",            r"\bNCEs?\b|notas? de cr[ée]dito [àa] exporta"),
    ("debenture",      r"debêntures?"),
    ("locacao",        r"contratos? de loca[çc][ãa]o|alugu[ée]is"),
]
GATILHO_LASTRO = re.compile(r"lastro|direitos credit[óo]rios", re.I)


def _limpo(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "")


def _papel(termo: str, tipo_titulo: str) -> str | None:
    n = F.norm(termo)
    for padrao, papel in PAPEIS:
        if re.search(padrao, n):
            if papel == "emissor" and tipo_titulo in ("CRI", "CRA"):
                return "securitizadora"   # no CRI/CRA a “Emissora” é a securitizadora
            return papel
    return None


def _nome(antes: str) -> str | None:
    """Texto antes do CNPJ → nome da parte, ou None se não houver a qualificação societária."""
    # a qualificação tem várias vírgulas (", sociedade anônima, inscrita…"): da última para a primeira, o nome
    # é o primeiro segmento que começa em maiúscula
    for q in reversed(list(QUALIF_RE.finditer(antes))):
        seg = SEPARADOR_RE.split(antes[:q.start()])[-1].strip()
        seg = re.sub(r"^(?:e|ainda|bem como|de um lado|de outro lado)\s+", "", seg).strip()
        if 3 <= len(seg) <= 150 and seg[0].isupper():
            return seg
    return None


def _trecho(t: str, ini: int, fim: int, folga: int = 160) -> str:
    return t[max(0, ini - folga):min(len(t), fim + folga)].strip()


def extrair(texto: str, tipo_titulo: str) -> dict:
    """Texto de um documento → {'partes': [...], 'garantias': [...], 'lastro': [...]} (sem tocar no banco)."""
    t = _limpo(texto)
    partes, vistos = [], set()
    cnpjs = list(CNPJ_RE.finditer(t))
    for i, m in enumerate(cnpjs):
        prox = cnpjs[i + 1].start() if i + 1 < len(cnpjs) else len(t)
        depois = t[m.end():min(prox, m.end() + 700)]
        termo = TERMO_RE.search(depois)
        papel = _papel(termo.group(1), tipo_titulo) if termo else None
        if not papel:
            continue
        cnpj = F.fmt_cnpj(m.group(0))
        if (papel, cnpj) in vistos:
            continue
        vistos.add((papel, cnpj))
        nome = _nome(t[max(0, m.start() - 450):m.start()])
        partes.append({"papel": papel, "cnpj": cnpj, "nome": nome,
                       "evidencia": _trecho(t, m.start(), m.end() + (termo.end() if termo else 0), 120),
                       "confianca": 0.8})

    baixo = t.lower()
    garantias = []
    for tipo, padrao in GARANTIAS:
        achados = []
        for m in re.finditer(padrao, baixo):
            if tipo != "sem_garantia" and NEGACAO.search(baixo[max(0, m.start() - 60):m.start()]):
                continue
            achados.append(m)
        if achados:
            m = achados[0]
            garantias.append({"tipo": tipo, "descricao": f"{len(achados)} menção(ões) no documento",
                              "evidencia": _trecho(t, m.start(), m.end()), "confianca": 0.6})

    lastro = []
    if tipo_titulo in ("CRI", "CRA"):
        janelas = [(max(0, g.start() - 400), g.end() + 400) for g in GATILHO_LASTRO.finditer(t)]
        for tipo, padrao in LASTRO:
            for ini, fim in janelas:
                m = re.search(padrao, t[ini:fim], re.I)
                if m:
                    lastro.append({"tipo_lastro": tipo, "evidencia": _trecho(t, ini + m.start(), ini + m.end()),
                                   "confianca": 0.6})
                    break
        # "CPR" genérico também casa dentro de "CPR-F": fica só o mais específico
        if any(l["tipo_lastro"] == "CPR-F" for l in lastro):
            lastro = [l for l in lastro if l["tipo_lastro"] != "CPR"]
    return {"partes": partes, "garantias": garantias, "lastro": lastro}


def gravar(conn, doc_id: str, codigo: str, tipo_titulo: str, r: dict) -> None:
    from ingest_rf_cadastro import parte
    upsert(conn, "rf_partes", [parte(codigo, p["papel"], p["cnpj"], p["nome"], fonte="pdf", doc_id=doc_id,
                                     evidencia=p["evidencia"], confianca=p["confianca"]) for p in r["partes"]],
           conflict="chave")
    prestadores = {}
    for p in r["partes"]:
        prestadores.setdefault(p["papel"], []).append(p)
    linhas = []
    for g in r["garantias"]:
        quem = prestadores.get({"fianca": "fiador", "aval": "avalista"}.get(g["tipo"], ""), [])
        linhas.append({
            "chave": f"{codigo}|{g['tipo']}|pdf|{doc_id}", "codigo": codigo, "tipo": g["tipo"],
            "descricao": g["descricao"],
            "prestador_cnpj": quem[0]["cnpj"] if len(quem) == 1 else None,
            "prestador_nome": "; ".join(q["nome"] or q["cnpj"] for q in quem) or None,
            "fonte": "pdf", "doc_id": doc_id, "evidencia": g["evidencia"], "confianca": g["confianca"]})
    upsert(conn, "rf_garantias", linhas, conflict="chave")
    devedores = prestadores.get("devedor", [])
    upsert(conn, "rf_lastro", [{
        "chave": f"{codigo}|{l['tipo_lastro']}|pdf|{doc_id}", "codigo": codigo, "tipo_lastro": l["tipo_lastro"],
        "devedor_cnpj": devedores[0]["cnpj"] if len(devedores) == 1 else None,
        "devedor_nome": devedores[0]["nome"] if len(devedores) == 1 else None,
        "descricao": None, "fonte": "pdf", "doc_id": doc_id, "evidencia": l["evidencia"],
        "confianca": l["confianca"]} for l in r["lastro"]], conflict="chave")


def processar(conn, codigo: str | None = None, todos: bool = False) -> int:
    where, args = ["d.texto_extraido IS NOT NULL"], []
    if codigo:
        where.append("x.codigo = ?")
        args.append(codigo)
    elif not todos:
        where.append("d.regras_em IS NULL")
    rows = conn.execute(
        "SELECT d.doc_id, x.codigo, COALESCE(a.tipo, '') , d.texto_extraido FROM rf_docs d "
        "JOIN rf_doc_ativo x ON x.doc_id = d.doc_id LEFT JOIN rf_ativos a ON a.codigo = x.codigo "
        f"WHERE {' AND '.join(where)}", args).fetchall()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for doc_id, cod, tipo, txt in rows:
        tipo = tipo or F.tipo_por_codigo(cod)
        r = extrair(txt, tipo)
        print(f"  {cod} · {doc_id}: {len(r['partes'])} partes, {len(r['garantias'])} garantias, "
              f"{len(r['lastro'])} lastros")
        gravar(conn, doc_id, cod, tipo, r)
        conn.execute("UPDATE rf_docs SET regras_em = ? WHERE doc_id = ?", (agora, doc_id))
    conn.commit()
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--codigo")
    p.add_argument("--todos", action="store_true")
    a = p.parse_args()
    n = processar(get_db(), (a.codigo or "").upper() or None, a.todos)
    print(f"{n} par(es) documento × título lido(s)")


if __name__ == "__main__":
    main()
