"""
Segmentador de notas explicativas e dicionário canônico de seções da DFP e ITR (Etapa 9, itens 9.10 e 9.11).

Identifica cabeçalhos de nota ("Nota 26 - Imposto de Renda e Contribuição Social", "12. Imobilizado", etc.),
segmenta o texto do documento em seções com posição em caracteres e páginas no PDF, e mapeia os títulos
para seções contábeis canônicas (ir_csll, subvencoes, divida_emprestimos, imobilizado, etc.).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Seções canônicas de demonstrações financeiras (Etapa 9.11)
CANONICAS: tuple[str, ...] = (
    "ir_csll",
    "subvencoes",
    "tributos_recuperar",
    "imobilizado",
    "intangivel",
    "provisoes",
    "divida_emprestimos",
    "partes_relacionadas",
    "patrimonio_liquido",
    "segmentos",
    "arrendamentos",
    "eventos_subsequentes",
    "instrumentos_financeiros",
)

# Apelidos e sinônimos comuns aceitos na busca por seção
ALIASES: dict[str, str] = {
    "emprestimos": "divida_emprestimos",
    "emprestimo": "divida_emprestimos",
    "financiamentos": "divida_emprestimos",
    "divida": "divida_emprestimos",
    "debentures": "divida_emprestimos",
    "ir": "ir_csll",
    "csll": "ir_csll",
    "imposto_renda": "ir_csll",
    "tributos": "ir_csll",
    "impostos": "ir_csll",
    "incentivos": "subvencoes",
    "subvencao": "subvencoes",
    "contingencias": "provisoes",
    "processos_judiciais": "provisoes",
    "pl": "patrimonio_liquido",
    "capital_social": "patrimonio_liquido",
    "segmento": "segmentos",
    "arrendamento": "arrendamentos",
    "direito_de_uso": "arrendamentos",
    "leases": "arrendamentos",
}

# Padrões para reconhecimento de títulos canônicos (português e inglês)
MAPA_CANONICO: list[tuple[str, re.Pattern]] = [
    ("subvencoes", re.compile(
        r"\b(subvenc\w*|incentivo\w*\s+fisc\w*|beneficio\w*\s+fisc\w*|lei do bem|sudene|sudam|government grant\w*|tax incentive\w*)\b"
    )),
    ("ir_csll", re.compile(
        r"\b(imposto\w*.*renda|imposto\w*.*lucro|irpj|csll|tributo\w*.*lucro|tributo\w*.*renda|income tax\w*)\b"
    )),
    ("tributos_recuperar", re.compile(
        r"\b(tributo\w*.*recuperar|imposto\w*.*recuperar|credito\w*.*tributario\w*|recoverable tax\w*)\b"
    )),
    ("imobilizado", re.compile(
        r"\b(imobilizado\w*|property.*plant|fixed asset\w*)\b"
    )),
    ("intangivel", re.compile(
        r"\b(intangivel\w*|goodwill|agio|intangible\w*)\b"
    )),
    ("provisoes", re.compile(
        r"\b(provis\w*|contingenc\w*|processo\w*.*judicia\w*|litigio\w*)\b"
    )),
    ("divida_emprestimos", re.compile(
        r"\b(emprestim\w*|financiam\w*|debentur\w*|borrow\w*|loan\w*|divida\w*)\b"
    )),
    ("partes_relacionadas", re.compile(
        r"\b(partes?\s+relacionad\w*|related part\w*)\b"
    )),
    ("patrimonio_liquido", re.compile(
        r"\b(patrimonio\s+liquido|capital\s+social|equity)\b"
    )),
    ("segmentos", re.compile(
        r"\b(segmento\w*|operating segment\w*)\b"
    )),
    ("arrendamentos", re.compile(
        r"\b(arrendament\w*|direito\s+de\s+uso|lease\w*|right of use)\b"
    )),
    ("eventos_subsequentes", re.compile(
        r"\b(eventos?\s+subsequente\w*|fatos?\s+posterior\w*|subsequent event\w*)\b"
    )),
    ("instrumentos_financeiros", re.compile(
        r"\b(instrumento\w*.*financeiro\w*|risco\w*.*financeiro\w*|financial instrument\w*)\b"
    )),
]

# Numerais romanos válidos para numeração de notas (I a XXXIX, evitando falsos positivos como CVM, CPC, IFRS)
_ROMANO = r"(?:X{1,3}(?:IX|IV|V?I{0,3})?|IX|IV|V?I{1,3}|V)"

# Regex para cabeçalho de notas explicativas:
# "Nota 26 - Imposto de Renda e Contribuição Social", "26. Imobilizado", "34) IMPOSTO...", "Nota I - ..."
RE_HEADER = re.compile(
    rf'(?m)^[ \t\f]*(?:(?:Nota|NOTA|Note|NOTE)\s+)?(\d{{1,2}}(?:\.\d{{1,2}})*|{_ROMANO})[\.\)]?[\s–-]+([A-ZÁÉÍÓÚÇ][^\n]{{3,120}})$'
)

# Regex para linhas de tabela financeira com múltiplos números no final (ex: "Receita ... 10.000 20.000 (5.000)")
_RE_TABELA_NUMEROS = re.compile(r'\s+[\d\.,]{3,}(?:\s+[\d\.,\(\)\-]+)+\s*$')


@dataclass(frozen=True)
class SecaoNota:
    numero: str
    titulo: str
    secao_canonica: str | None
    pos_inicio: int
    pos_fim: int
    pagina_inicio: int | None
    pagina_fim: int | None
    is_primaria: bool


def normalizar_titulo(titulo: str) -> str:
    """Remove acentos, converte para minúsculas e colapsa espaços e pontuações."""
    s = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def identificar_secao_canonica(titulo: str) -> str | None:
    """Mapeia um título de nota explicativa para sua chave canônica, ou None se não reconhecido."""
    t = normalizar_titulo(titulo)
    for can, pat in MAPA_CANONICO:
        if pat.search(t):
            return can
    return None


def resolver_chave_secao(secao: str | None) -> str | None:
    """Resolve uma string de seção (canônica, alias ou termo descritivo) para a chave canônica correspondente."""
    if not secao:
        return None
    s = secao.strip().lower()
    if s in CANONICAS:
        return s
    if s in ALIASES:
        return ALIASES[s]
    # Tenta identificar por texto natural
    return identificar_secao_canonica(s)


def eh_linha_tabela_ou_demonstrativo(linha: str) -> bool:
    """Verifica se uma linha parece ser item de balanço/DRE/tabela com múltiplos valores numéricos."""
    return bool(_RE_TABELA_NUMEROS.search(linha.strip()))


def extrair_secoes_documento(texto: str) -> list[SecaoNota]:
    """Extrai todas as seções e notas explicativas do texto de um documento DFP ou ITR.

    Retorna lista de SecaoNota ordenadas por pos_inicio.
    Se o texto contém quebras de página com form-feed (\\f), calcula pagina_inicio e pagina_fim.
    """
    if not texto:
        return []

    matches = list(RE_HEADER.finditer(texto))
    if not matches:
        return []

    tem_paginas = "\f" in texto
    candidatos: list[tuple[str, str, int, int]] = []
    for i, m in enumerate(matches):
        num = m.group(1)
        tit = m.group(2).strip()
        # Descarta linhas que parecem tabela contábil com múltiplos números
        if eh_linha_tabela_ou_demonstrativo(tit):
            continue
        leading_ws = len(m.group(0)) - len(m.group(0).lstrip(" \t\f\r\n"))
        pos_ini = m.start() + leading_ws
        pos_fim = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
        span = pos_fim - pos_ini
        # Linhas de sumário/índice com pontilhado ou span mínimo
        if span < 120 and ("..." in tit or re.search(r"\.{3,}|\s+\d+$", tit)):
            continue
        candidatos.append((num, tit, pos_ini, pos_fim))

    secoes: list[SecaoNota] = []
    for j, (num, tit, p_ini, _) in enumerate(candidatos):
        p_fim = candidatos[j + 1][2] if j + 1 < len(candidatos) else len(texto)
        can = identificar_secao_canonica(tit)
        pag_ini = 1 + texto[:p_ini].count("\f") if tem_paginas else None
        pag_fim = 1 + texto[:p_fim].count("\f") if tem_paginas else None

        # Primária: nota de nível superior (sem ponto sub-seção) e número >= 3
        # (notas 1 e 2 são contexto operacional e resumo de políticas contábeis)
        is_num = num.isdigit()
        is_primaria = ("." not in num) and (not is_num or int(num) >= 3)

        secoes.append(SecaoNota(
            numero=num,
            titulo=tit,
            secao_canonica=can,
            pos_inicio=p_ini,
            pos_fim=p_fim,
            pagina_inicio=pag_ini,
            pagina_fim=pag_fim,
            is_primaria=is_primaria,
        ))
    return secoes


def obter_secao_por_chave(secoes: list[SecaoNota], chave: str) -> SecaoNota | None:
    """Busca a melhor seção correspondente à chave canônica em uma lista de seções extraídas.

    Prioriza notas primárias (top-level fora da nota 2 de políticas) e maior span de texto.
    """
    can = resolver_chave_secao(chave)
    if not can:
        return None
    matches = [s for s in secoes if s.secao_canonica == can]
    if not matches:
        return None
    primarias = [s for s in matches if s.is_primaria]
    candidatos = primarias if primarias else matches
    return max(candidatos, key=lambda s: s.pos_fim - s.pos_inicio)


def encontrar_secao_do_offset(secoes: list[SecaoNota], offset: int) -> SecaoNota | None:
    """Retorna a seção que contém o caractere na posição offset, ou None se fora das seções."""
    if not secoes or offset < 0:
        return None
    for s in secoes:
        if s.pos_inicio <= offset < s.pos_fim:
            return s
    return None
