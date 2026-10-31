"""
Extração por regra das partes, garantias e lastro de um título a partir do texto dos documentos (rf_docs).

Determinística e sem chamada a modelo: lê o que a escritura ou o termo de securitização escreve de
forma padronizada.
- Partes: cada CNPJ do texto, com o nome que vem antes ("RUMO S.A., sociedade por ações…") e o termo
  definido que vem depois (“Emissora”, “Fiadora”, “Devedora”, “Agente Fiduciário”…), que dá o papel.
  CNPJ sem termo definido reconhecível não vira parte.
  Também em estilo de definição ("“Devedora” significa a FS …, inscrita no CNPJ …") e apelido designado depois
  ("fiança pela JBS (que passará a ser designada como “Fiadora”)").
- Garantias: vocabulário (alienação/cessão fiduciária, fiança, aval, hipoteca, penhor, fundo de reserva,
  subordinação, coobrigação, garantia flutuante, quirografária), descartando menção negada antes ("não contará
  com fiança") ou depois ("Coobrigação da Emissora: Não há") e enumerações genéricas (definição de “Ônus”).
  Uma linha por tipo e documento, com o primeiro trecho como evidência e o `escopo`: 'titulo' ou 'lastro'.
- Lastro (CRI/CRA): instrumentos citados perto de "lastro", "direitos creditórios" ou "créditos do agronegócio".
Antes de tudo, tira o ruído de página (DocuSign, "Página N de M") e corta o anexo com o histórico de emissões do
agente fiduciário, que descreve outros títulos. Testado contra trechos de dois termos reais
(tests/fixtures/rf/termos_reais.py).

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
# termo definido entre parênteses depois do CNPJ: (“Emissora”) · ("Fiadora") · (doravante denominada “Devedora”)
TERMO_RE = re.compile(r"\(\s*(?:[^()“”\"]{0,80}?)?[“\"']\s*([^”\"']{3,60}?)\s*[”\"']")
# termos entre aspas dentro de uma definição: “Devedora” significa…, "JBS"
ASPAS_RE = re.compile(r"[“\"]\s*([^”\"“]{2,45}?)\s*[”\"]")
# o nome termina na vírgula que abre a qualificação ("RUMO S.A., sociedade por ações…")
_QUALIF = r",\s*(?:sociedade|companhia|institui|pessoa|empresa|fundo|com sede|inscrit|com registro|neste ato|atuando)"
# definição: “Devedora” significa a FS Indústria … Ltda., sociedade…  → o nome vem depois do artigo
# (o PDF em duas colunas às vezes cola o termo no nome: “Devedora a JBS S.A., sociedade…)
NOME_DEF_RE = re.compile(r"(?:significa|:|,|[“\"][A-ZÀ-Ý]\w+)\s+(?:a|o)\s+([A-ZÀ-Ý][^,;:“”\"()]{1,140}?)" + _QUALIF)
# qualificação: VIRGO COMPANHIA DE SECURITIZAÇÃO, sociedade por ações…  → o primeiro nome com qualificação
NOME_QUAL_RE = re.compile(r"(?<![\w.])([A-ZÀ-Ý][^,;:“”\"()]{1,140}?)" + _QUALIF)
# pedaços de endereço também vêm antes de ", inscrita no CNPJ": não são nome
NAO_NOME_RE = re.compile(r"^(?:CEP|Bairro|Rua|Av\.?|Avenida|Estrada|Rodovia|Distrito|Sala|Estado|Cidade)\b|\bn[ºo°]\s*\d"
                         r"|^[\d\s.-]+$")
# onde começa a cláusula de uma parte: ';', fim de definição antes de aspas, ':' de "as partes:", enumeração
INICIO_CLAUSULA_RE = re.compile(r";|\.\s+(?=[“\"])|:\s|\(\s*[ivxlc]+\s*\)|\b[a-h]\)")
# apelido designado depois: "fiança pela JBS (que passará a ser designada como “Fiadora”)"
DESIGNACAO_RE = re.compile(
    r"\b(?:pela|pelo|da|do|a|o)\s+([A-ZÀ-Ý][\w.&-]{1,30})\s*\(\s*(?:que\s+passar[áa]\s+a\s+ser\s+)?"
    r"(?:designad[ao]|denominad[ao])\s+(?:como\s+)?[“\"]([^”\"]{3,40})[”\"]")

# termo definido (normalizado) → papel; a ordem importa ("agente fiduciário" antes de qualquer outro)
PAPEIS = [
    (r"agente fiduci", "agente_fiduciario"),
    (r"securitizador", "securitizadora"),
    (r"^emissora$|^companhia$|^emitente$", "emissor"),
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
    ("sem_garantia",         r"n[ãa]o (?:contar[ãa]o com|haver[áa]|h[áa]|ser[ãa]o constitu[íi]das|ser[ãa]o?)\s+"
                             r"(?:com\s+)?(?:quaisquer\s+|qualquer\s+|nenhuma\s+)?garantias?"
                             r"(?:\s+(?:espec[íi]ficas|reais|pessoais|fidejuss[óo]rias))"),
]
_TIPOS_ENUMERAVEIS = [t for t, _ in GARANTIAS if t not in ("sem_garantia", "quirografaria")]
# Garantias que a escritura precisa amarrar ao próprio título: medido em 366 escrituras contra a espécie do SND
# (stress/st8_medir_extracao.py), a menção solta dava 34% de garantia real falsa em quirografárias (ônus permitidos,
# vencimento antecipado, definições, emissões de terceiros). Sinais: termo definido (“Cessão Fiduciária”, “Contrato
# de Alienação Fiduciária”), a cláusula de espécie ou a de "em garantia do … pagamento".
COM_SINAL = {"alienacao_fiduciaria", "cessao_fiduciaria", "penhor", "hipoteca", "fianca", "aval"}
_SINAL_GARANTE = re.compile(r"em garantia d[oa]s? (?:fiel|integral|pontual|cumprimento|pagamento|deb[êe]ntures|cr[ai]s?\b)"
                            r"|em garantia,? ser[áa]o? constitu|obriga[çc][õo]es garantidas")
_SINAL_ESPECIE = re.compile(r"esp[ée]cie (?:com garantia|quirograf|subordinada|real)|garantia adicional "
                            r"(?:real|fidejuss)|garantia fidejuss[óo]ria")


def _amarrada_ao_titulo(baixo: str, padrao: str) -> bool:
    if re.search(rf"[“\"](?:contrato de |instrumento (?:particular )?de )?(?:{padrao})[^”\"]{{0,40}}[”\"]", baixo):
        return True
    for sinal, alcance in ((_SINAL_GARANTE, 500), (_SINAL_ESPECIE, 600)):
        for m in sinal.finditer(baixo):
            if re.search(padrao, baixo[m.start():m.end() + alcance]):
                return True
    return False
# "não conversíveis em ações" descreve a debênture, não nega a garantia que vem depois
NEGACAO_ANTES = re.compile(r"\b(n[ãa]o(?! convers[íi]ve)|sem|nenhuma|inexist\w*|exceto)\b[^.;]{0,40}$")
# "Coobrigação da Emissora: Não há" · "Garantia Flutuante: Não haverá"
NEGACAO_DEPOIS = re.compile(r"^[^.;]{0,25}?:\s*n[ãa]o\b|^\s*n[ãa]o\s+h[áa]\b")
# definição genérica ("“Ônus” significa qualquer hipoteca, penhor…"): não é garantia do título
DEFINICAO_GENERICA = re.compile(r"[“\"](?:[ÔôOo]nus|Gravames?|Onerar)[”\"]")
# lista de vedações: "não implicam na criação de qualquer hipoteca, penhor, usufruto… ou outro gravame"
VEDACAO_GENERICA = re.compile(r"outr[oa]s? (?:gravames?|[ôo]nus|encargos?)|qualquer (?:gravame|[ôo]nus)")

LASTRO = [
    ("CPR-F",          r"\bCPR[- ]?F(?:inanceiras?)?\b|c[ée]dulas? de produto rural financeira"),
    ("CPR",            r"c[ée]dulas? de produto rural(?! financeira)"),
    ("CDCA",           r"\bCDCAs?\b|certificados? de direitos credit[óo]rios do agroneg[óo]cio"),
    ("CCB",            r"\bCCBs?\b|c[ée]dulas? de cr[ée]dito banc[áa]rio"),
    ("CCI",            r"\bCCIs?\b|c[ée]dulas? de cr[ée]dito imobili[áa]rio"),
    ("nota_comercial", r"notas? comercia(?:l|is)"),
    ("NCE",            r"\bNCEs?\b|notas? de cr[ée]dito [àa] exporta"),
    ("debenture",      r"debêntures?"),
    ("locacao",        r"contratos? de loca[çc][ãa]o|alugu[ée]is"),
]
GATILHO_LASTRO = re.compile(r"lastro|direitos credit[óo]rios|cr[ée]ditos do agroneg[óo]cio|cr[ée]ditos imobili[áa]rios",
                            re.I)
# frase sobre o lastro (e não sobre o título): a garantia é do instrumento que paga o CRI/CRA
FRASE_LASTRO = re.compile(r"\bCPR|CDCA|\bCCB|\bCCI|lastro|direitos credit[óo]rios|cr[ée]ditos do agroneg|debêntures|"
                          r"escritura de emiss|avalista|devedora|nota comercial", re.I)
FRASE_TITULO = re.compile(r"sobre os CR[AI]\b|\bdos CR[AI]\b|os CR[AI] (?:n[ãa]o )?contar", re.I)

# ruído que o PDF intercala no meio das frases
_RUIDO = [
    re.compile(r"DocuSign Envelope ID:\s*[0-9A-F-]{36}", re.I),
    re.compile(r"P[áa]gina \d+ de \d+", re.I),
]
# anexo com outras emissões do agente fiduciário: tudo dali é de outros títulos
_ANEXO_TERCEIROS = re.compile(r"hist[óo]rico de emiss[õo]es|emiss[õo]es (?:de valores mobili[áa]rios )?em que "
                              r"(?:o agente fiduci[áa]rio )?(?:atua|tenha atuado)", re.I)


def _limpo(texto: str) -> str:
    t = texto or ""
    for r in _RUIDO:
        t = r.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    # CNPJ quebrado na linha: "46.710.597/0001- 69"
    return re.sub(r"(\d{4})\s*-\s+(\d{2})\b", r"\1-\2", t)


# ficha de outra emissão listada pelo agente fiduciário (Resolução CVM 17, art. 6º), no corpo da escritura ou no
# relatório anual: "Valor Total da Emissão R$ … Espécie … Garantias Fiança; … Enquadramento Adimplência Financeira"
# A quebra de coluna do PDF embaralha os rótulos ("Valor Total da R$ 800.000.000,00 Emissão Quantidade … Espécie
# Real Garantias Cessão Fiduciária e Fiança Data de 10/06/2027 Vencimento"); outro layout é "Espécie e garantias
# envolvidas: … Data de emissão".
_FICHA_TERCEIROS = re.compile(
    r"(?:valor total da\b|volume total previsto).{0,700}?(?:enquadramento|inadimplementos? no per[íi]odo)"
    r"|(?:valor total da\b|volume total previsto).{0,400}?quantidade.{0,300}?esp[ée]cie.{0,400}?vencimento"
    r"|esp[ée]cie e garantias envolvidas:.{0,600}?data de (?:emiss|venc)", re.I)


def _sem_anexo_de_terceiros(t: str) -> str:
    """Corta no anexo com o histórico de emissões do agente fiduciário (só depois de 30% do texto: o índice, no
    começo, também cita o anexo) e tira as fichas de outras emissões que aparecem no corpo."""
    for m in _ANEXO_TERCEIROS.finditer(t):
        if m.start() > 0.3 * len(t):
            t = t[:m.start()]
            break
    return _FICHA_TERCEIROS.sub(" ", t)


def _papel(termo: str, tipo_titulo: str) -> str | None:
    n = F.norm(termo)
    for padrao, papel in PAPEIS:
        if re.search(padrao, n):
            if papel == "emissor" and tipo_titulo in ("CRI", "CRA"):
                return "securitizadora"   # no CRI/CRA a “Emissora” é a securitizadora
            return papel
    return None


def _nome(clausula: str) -> str | None:
    """Primeiro nome com qualificação societária na cláusula (definição antes de qualificação)."""
    for regex in (NOME_DEF_RE, NOME_QUAL_RE):
        for m in regex.finditer(clausula):
            nome = re.sub(r"^(?:e|ainda|bem como|de um lado|de outro lado)\s+", "", m.group(1)).strip()
            if 3 <= len(nome) <= 150 and not NAO_NOME_RE.search(nome):
                return nome
    return None


def _clausula(t: str, fim: int) -> str:
    """Texto da cláusula que termina no CNPJ: do início de cláusula mais próximo que ainda contenha um nome com
    qualificação (até 700 caracteres atrás). Há ':' dentro da própria definição ("“Companhia”: operacional")."""
    trecho = t[max(0, fim - 700):fim]
    for m in reversed(list(INICIO_CLAUSULA_RE.finditer(trecho))):
        if _nome(trecho[m.start():]):
            return trecho[m.start():]
    return trecho


def _trecho(t: str, ini: int, fim: int, folga: int = 160) -> str:
    return t[max(0, ini - folga):min(len(t), fim + folga)].strip()


def _frase(t: str, ini: int, fim: int) -> str:
    a = max(t.rfind(". ", 0, ini), t.rfind("; ", 0, ini))
    b = min([x for x in (t.find(". ", fim), t.find("; ", fim)) if x >= 0] or [len(t)])
    return t[a + 1:b]


def _partes(t: str, tipo_titulo: str) -> list[dict]:
    partes, vistos, apelidos = [], set(), {}
    cnpjs = list(CNPJ_RE.finditer(t))
    for i, m in enumerate(cnpjs):
        cnpj = F.fmt_cnpj(m.group(0))
        if not cnpj:
            continue
        clausula = _clausula(t, m.start())
        prox = cnpjs[i + 1].start() if i + 1 < len(cnpjs) else len(t)
        # 1) termo entre parênteses logo depois do CNPJ (qualificação); 2) termos da própria definição, antes dele
        depois = TERMO_RE.search(t[m.end():min(prox, m.end() + 400)])
        termos = ([depois.group(1)] if depois else []) + ASPAS_RE.findall(clausula)
        papeis = []
        for termo in termos:
            papel = _papel(termo, tipo_titulo)
            if papel and papel not in papeis:
                papeis.append(papel)
        nome = _nome(clausula)
        for termo in ASPAS_RE.findall(clausula):
            apelidos.setdefault(F.norm(termo), (cnpj, nome))
        if nome:
            apelidos.setdefault(F.norm(nome.split()[0]), (cnpj, nome))
        if not papeis:
            continue
        papel = papeis[0]   # o termo mais próximo do CNPJ manda; "Emissora" e "Securitizadora" dão no mesmo
        if (papel, cnpj) in vistos:
            continue
        vistos.add((papel, cnpj))
        partes.append({"papel": papel, "cnpj": cnpj, "nome": nome,
                       "evidencia": _trecho(t, m.start(), m.end(), 160), "confianca": 0.8})
    # apelido designado depois ("fiança pela JBS (que passará a ser designada como “Fiadora”)")
    for m in DESIGNACAO_RE.finditer(t):
        papel = _papel(m.group(2), tipo_titulo)
        alvo = apelidos.get(F.norm(m.group(1)))
        if not papel or not alvo or (papel, alvo[0]) in vistos:
            continue
        vistos.add((papel, alvo[0]))
        partes.append({"papel": papel, "cnpj": alvo[0], "nome": alvo[1],
                       "evidencia": _trecho(t, m.start(), m.end(), 120), "confianca": 0.7})
    return partes


def _escopo(frase: str, tipo_titulo: str, tipo: str) -> str:
    if tipo_titulo not in ("CRI", "CRA") or tipo == "sem_garantia" or FRASE_TITULO.search(frase):
        return "titulo"
    return "lastro" if FRASE_LASTRO.search(frase) else "titulo"


def _garantias(t: str, tipo_titulo: str, exigir_sinal: bool = True) -> list[dict]:
    baixo = t.lower()
    tipos_em = {tipo: [m.start() for m in re.finditer(p, baixo)] for tipo, p in GARANTIAS}
    out = []
    for tipo, padrao in GARANTIAS:
        achados = []
        for m in re.finditer(padrao, baixo):
            if tipo != "sem_garantia":
                if NEGACAO_ANTES.search(baixo[max(0, m.start() - 60):m.start()]):
                    continue
                if NEGACAO_DEPOIS.search(baixo[m.end():m.end() + 40]):
                    continue
                # enumeração de tipos (definição de “Ônus”, lista de vedações): não descreve garantia alguma
                vizinhos = {o for o in _TIPOS_ENUMERAVEIS
                            if any(abs(x - m.start()) <= 150 for x in tipos_em[o])}
                if len(vizinhos) >= 3 or DEFINICAO_GENERICA.search(t[max(0, m.start() - 200):m.start()]) \
                        or VEDACAO_GENERICA.search(baixo[max(0, m.start() - 200):m.end() + 200]):
                    continue
            achados.append(m)
        if achados and exigir_sinal and tipo in COM_SINAL and not _amarrada_ao_titulo(baixo, padrao):
            continue
        if achados:
            m = achados[0]
            out.append({"tipo": tipo, "descricao": f"{len(achados)} menção(ões) no documento",
                        "escopo": _escopo(_frase(t, m.start(), m.end()), tipo_titulo, tipo),
                        "evidencia": _trecho(t, m.start(), m.end()), "confianca": 0.6})
    return out


def _lastro(t: str) -> list[dict]:
    janelas = [(max(0, g.start() - 400), g.end() + 400) for g in GATILHO_LASTRO.finditer(t)]
    lastro = []
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
    return lastro


def extrair(texto: str, tipo_titulo: str, exigir_sinal: bool = True) -> dict:
    """Texto de um documento → {'partes': [...], 'garantias': [...], 'lastro': [...]} (sem tocar no banco).
    `exigir_sinal=False` para texto que já é só sobre o título (descrição das garantias da oferta na CVM)."""
    t = _sem_anexo_de_terceiros(_limpo(texto))
    return {"partes": _partes(t, tipo_titulo), "garantias": _garantias(t, tipo_titulo, exigir_sinal),
            "lastro": _lastro(t) if tipo_titulo in ("CRI", "CRA") else []}


def gravar(conn, doc_id: str, codigo: str, tipo_titulo: str, r: dict, fonte: str = "pdf") -> None:
    """`fonte`: 'pdf' (texto do documento) ou 'cvm_oferta' (descrição do requerimento da Resolução 160)."""
    from ingest_rf_cadastro import parte
    upsert(conn, "rf_partes", [parte(codigo, p["papel"], p["cnpj"], p["nome"], fonte=fonte, doc_id=doc_id,
                                     evidencia=p["evidencia"], confianca=p["confianca"]) for p in r["partes"]],
           conflict="chave")
    prestadores = {}
    for p in r["partes"]:
        prestadores.setdefault(p["papel"], []).append(p)
    linhas = []
    for g in r["garantias"]:
        quem = prestadores.get({"fianca": "fiador", "aval": "avalista"}.get(g["tipo"], ""), [])
        if not quem and g["tipo"] in ("fianca", "aval"):
            quem = prestadores.get("coobrigado", []) or prestadores.get("garantidor", [])
        linhas.append({
            "chave": f"{codigo}|{g['tipo']}|{fonte}|{doc_id}", "codigo": codigo, "tipo": g["tipo"],
            "escopo": g.get("escopo"), "descricao": g["descricao"],
            "prestador_cnpj": quem[0]["cnpj"] if len(quem) == 1 else None,
            "prestador_nome": "; ".join(q["nome"] or q["cnpj"] for q in quem) or None,
            "fonte": fonte, "doc_id": doc_id, "evidencia": g["evidencia"], "confianca": g["confianca"]})
    upsert(conn, "rf_garantias", linhas, conflict="chave")
    devedores = prestadores.get("devedor", [])
    upsert(conn, "rf_lastro", [{
        "chave": f"{codigo}|{l['tipo_lastro']}|{fonte}|{doc_id}", "codigo": codigo, "tipo_lastro": l["tipo_lastro"],
        "devedor_cnpj": devedores[0]["cnpj"] if len(devedores) == 1 else None,
        "devedor_nome": devedores[0]["nome"] if len(devedores) == 1 else None,
        "descricao": None, "fonte": fonte, "doc_id": doc_id, "evidencia": l["evidencia"],
        "confianca": l["confianca"]} for l in r["lastro"]], conflict="chave")


EMISSAO_RE = re.compile(r"escritura|aditamento|termo de securitizacao|termo de emissao")
NAO_EMISSAO_RE = re.compile(r"prospecto|relatorio (?:anual )?d[oe] agente|anuncio de|aviso ao mercado|lamina")


def documento_de_emissao(origem: str | None, rotulo: str, texto: str | None) -> bool:
    """Só a escritura, o termo de securitização e os aditamentos descrevem as partes e as garantias do título. O
    prospecto (seção de relacionamento com os coordenadores), o relatório do agente fiduciário (lista as outras
    emissões dele) e os anúncios citam garantias de outras operações: ficam na busca, fora da extração.
    PDF passado à mão (--url/--arquivo) conta como documento de emissão."""
    if origem in ("url", "arquivo"):
        return True
    r = F.norm(rotulo)
    if NAO_EMISSAO_RE.search(r):
        return False
    if EMISSAO_RE.search(r):
        return True
    capa = F.norm((texto or "")[:1500])
    return bool(EMISSAO_RE.search(capa)) and not NAO_EMISSAO_RE.search(capa)


def processar(conn, codigo: str | None = None, todos: bool = False) -> int:
    where, args = ["d.texto_extraido IS NOT NULL"], []
    if codigo:
        where.append("x.codigo = ?")
        args.append(codigo)
    elif not todos:
        where.append("d.regras_em IS NULL")
    rows = conn.execute(
        "SELECT d.doc_id, x.codigo, COALESCE(a.tipo, ''), d.texto_extraido, d.origem, "
        "COALESCE(d.categoria, '') || ' ' || COALESCE(d.tipo, '') || ' ' || COALESCE(d.especie, '') || ' ' || "
        "COALESCE(d.assunto, '') FROM rf_docs d "
        "JOIN rf_doc_ativo x ON x.doc_id = d.doc_id LEFT JOIN rf_ativos a ON a.codigo = x.codigo "
        f"WHERE {' AND '.join(where)}", args).fetchall()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for doc_id, cod, tipo, txt, origem, rotulo in rows:
        tipo = tipo or F.tipo_por_codigo(cod)
        r = extrair(txt, tipo) if documento_de_emissao(origem, rotulo, txt) else {"partes": [], "garantias": [], "lastro": []}
        print(f"  {cod} · {doc_id}: {len(r['partes'])} partes, {len(r['garantias'])} garantias, "
              f"{len(r['lastro'])} lastros")
        for t in ("rf_partes", "rf_garantias", "rf_lastro"):   # a regra mudou ou o doc deixou de ser de emissão
            conn.execute(f"DELETE FROM {t} WHERE doc_id = ? AND codigo = ? AND fonte = 'pdf'", (doc_id, cod))
        gravar(conn, doc_id, cod, tipo, r)
        conn.execute("UPDATE rf_docs SET regras_em = ? WHERE doc_id = ?", (agora, doc_id))
    conn.commit()
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--codigo")
    p.add_argument("--todos", action="store_true")
    a = p.parse_args()
    conn = get_db()
    F.garantir_schema_rf(conn)
    n = processar(conn, (a.codigo or "").upper() or None, a.todos)
    print(f"{n} par(es) documento × título lido(s)")


if __name__ == "__main__":
    main()
