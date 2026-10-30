"""
Fontes públicas de renda fixa (debêntures, CRI, CRA): URLs, leitura e mapeamento de colunas.

É o único lugar a mexer quando uma fonte muda de layout. Os ingestores (ingest_rf_cadastro.py,
ingest_rf_taxas.py) só chamam as funções daqui.

Os layouts abaixo foram escritos sem acesso às fontes (a rede da sessão em que o módulo foi criado
bloqueava todas). Por isso as colunas são procuradas por **apelidos** (sem acento e sem caixa), e o
`--verificar` baixa uma amostra de cada fonte e mostra quais campos foram encontrados. Rode-o antes
da primeira carga e sempre que um ingestor reclamar de coluna ausente:

    cd scripts/ingest && ../../.venv/bin/python rf_fontes.py --verificar

Cada URL pode ser trocada por variável de ambiente (RF_URL_*), sem mexer no código.

Fontes:
    SND (debentures.com.br)      características de todas as debêntures (texto delimitado)
    CVM dados abertos            ofertas registradas: OFERTA/DISTRIB (ritos 400/476 e Resolução 160)
    ANBIMA mercado secundário    taxas indicativas diárias de debêntures e de CRI/CRA ('@' como separador)
"""
import io
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

# ── URLs (sobrescrevíveis por ambiente) ──────────────────────────────────────

URL_SND_CARACTERISTICAS = os.environ.get(
    "RF_URL_SND",
    "https://www.debentures.com.br/exploreosnd/consultaadados/emissoesdedebentures/"
    "caracteristicas_e.asp?tip_deb=publicas&op_exc=False",
)
URL_CVM_OFERTAS = os.environ.get(
    "RF_URL_CVM_OFERTAS", "https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.zip")
# {aammdd} = data do arquivo (ex.: 261030)
URL_ANBIMA_DEB = os.environ.get(
    "RF_URL_ANBIMA_DEB", "https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{aammdd}.txt")
# CRI/CRA: não há arquivo diário em URL fixa (merc-sec-cri-cra/arqs/cr{aammdd}.txt deu 404 em 2026-10-30). A
# fonte é o dataset público "CRIs e CRAs - Precificação ANBIMA" do data.anbima.com.br, que só sai depois de um
# formulário (nome, e-mail, aceite dos termos): download manual, lido por `ingest_rf_taxas.py --arquivo`
# (parse_anbima_data_cri_cra). Fica vazio a menos que a ANBIMA volte a publicar um link direto.
URL_ANBIMA_CRI_CRA = os.environ.get("RF_URL_ANBIMA_CRI_CRA", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CVM-Research-Bot/1.0)"}


# ── Schema ───────────────────────────────────────────────────────────────────

MIGRACAO_RF = Path(__file__).parents[1] / "migrations" / "2026-10-30_renda_fixa.sql"


def garantir_schema_rf(conn) -> bool:
    """Cria as tabelas de renda fixa num banco anterior à Etapa 8. O DDL só usa IF NOT EXISTS, então é seguro;
    roda antes de qualquer download para o job semanal não falhar por falta da migração. True = criou."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rf_ativos'").fetchone():
        return False
    ddl = "\n".join(l for l in MIGRACAO_RF.read_text(encoding="utf-8").splitlines() if not l.startswith("."))
    conn.executescript(ddl)   # ".bail on" é comando do CLI do sqlite3, não SQL
    print(f"  tabelas de renda fixa criadas ({MIGRACAO_RF.name})")
    return True


# ── Normalização ─────────────────────────────────────────────────────────────

def norm(s) -> str:
    """'Código do Ativo' → 'codigo do ativo': sem acento, caixa baixa, espaços simples."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[\s_/.]+", " ", s).strip()


def cnpj_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def fmt_cnpj(s) -> str | None:
    """Qualquer grafia de CNPJ → 00.000.000/0000-00 (o formato de companies.cnpj). None se não tiver 14 dígitos."""
    d = cnpj_digitos(s)
    if len(d) != 14:
        return None
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def num_br(v) -> float | None:
    """'1.234,56' / '1234.56' / '108,5%' → float. Vazio, '-' e 'N/D' → None."""
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace("R$", "").strip()
    if s in ("", "-", "--", "nan", "N/D", "n/d", "NaN"):
        return None
    if "," in s or re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):   # '1.650' é milhar, '6.4' é decimal
        s = s.replace(".", "").replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return None if f != f else f


def data_br(v) -> str | None:
    """'30/10/2026' / '2026-10-30' / '30/10/26' → '2026-10-30'."""
    s = str(v or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            d = pd.to_datetime(s, format=fmt)
        except Exception:
            continue
        if pd.isna(d):                  # 'NaT' do CSV da CVM vira NaT sem erro, e NaT.isoformat() é 'NaT'
            return None
        return d.date().isoformat()
    return None


def texto(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return None if s in ("", "nan", "-", "--", "NaN", "NaT", "None", "N/D") else s


CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}")
ROTULO_DEVEDOR_RE = re.compile(r"(?:Devedor[a]?|Cedente|Originador[a]?|Emitente)\s*[:\-–]\s*", re.I)
FIM_NOME_RE = re.compile(r",|\(|\s[-–_]\s|\s(?:devidamente|inscrit|no\s+CNPJ|CNPJ|sociedade|institui|com\s+sede)", re.I)


def nome_antes_do_cnpj(txt: str | None, cnpj: str | None) -> str | None:
    """Nome que antecede o CNPJ no texto livre da Resolução 160 ("Devedora: X LTDA - CNPJ …", "JBS S.A., sociedade
    por ações…, inscrita no CNPJ sob o nº …"): do último rótulo até a primeira vírgula, parêntese, travessão ou
    qualificação."""
    if not (txt and cnpj):
        return None
    m = next((m for m in CNPJ_RE.finditer(txt) if fmt_cnpj(m.group()) == cnpj), None)
    if not m:
        return None
    seg = txt[:m.start()]
    rotulos = list(ROTULO_DEVEDOR_RE.finditer(seg))
    if rotulos:
        seg = seg[rotulos[-1].end():]
    nome = FIM_NOME_RE.split(seg, maxsplit=1)[0].strip(" \t\n-–_:;")
    return nome if 3 <= len(nome) <= 150 else None


def tipo_por_codigo(codigo: str) -> str:
    """CRA024004SB → CRA; CRI…→ CRI; RUMOB6/ERDVB4 (4 letras + série) → DEB."""
    c = (codigo or "").strip().upper()
    if c.startswith("CRA"):
        return "CRA"
    if c.startswith("CRI"):
        return "CRI"
    if re.fullmatch(r"[A-Z]{4}[A-Z0-9]{1,3}", c):
        return "DEB"
    return "OUTRO"


def tipo_por_descricao(s) -> str:
    n = norm(s)
    if "agroneg" in n or re.search(r"\bcra\b", n):
        return "CRA"
    if "imobiliari" in n or re.search(r"\bcri\b", n):
        return "CRI"
    if "debentur" in n:
        return "DEB"
    return "OUTRO"


def indexador_de(remuneracao) -> str | None:
    n = norm(remuneracao)
    if not n:
        return None
    for chave, rotulo in (("ipca", "IPCA"), ("igp m", "IGP-M"), ("igpm", "IGP-M"), ("di", "DI"),
                          ("cdi", "DI"), ("selic", "SELIC"), ("tr", "TR"), ("pre", "PRE"), ("prefix", "PRE")):
        if re.search(rf"\b{chave}", n):
            return rotulo
    return None


# ── Colunas por apelido ──────────────────────────────────────────────────────

class ColunaAusente(KeyError):
    pass


def achar_colunas(cabecalho: list[str], apelidos: dict[str, list[str]],
                  obrigatorias: tuple[str, ...] = ()) -> dict[str, str]:
    """campo canônico → nome da coluna real. Casa por igualdade normalizada e, se não houver, por prefixo.
    Falta de coluna obrigatória levanta ColunaAusente com o cabeçalho real, para corrigir o apelido."""
    por_norm = {norm(c): c for c in cabecalho}
    achado = {}
    for campo, nomes in apelidos.items():
        for nome in nomes:
            n = norm(nome)
            if n in por_norm:
                achado[campo] = por_norm[n]
                break
        else:
            for nome in nomes:
                n = norm(nome)
                cand = [c for k, c in por_norm.items() if k.startswith(n)]
                if len(cand) == 1:
                    achado[campo] = cand[0]
                    break
    faltam = [c for c in obrigatorias if c not in achado]
    if faltam:
        raise ColunaAusente(f"colunas ausentes {faltam}; cabeçalho recebido: {cabecalho}")
    return achado


def _valor(r: dict, mapa: dict, campo: str):
    col = mapa.get(campo)
    return r.get(col) if col else None


# ── SND: características das debêntures ──────────────────────────────────────

APELIDOS_SND = {
    "codigo":            ["Codigo do Ativo", "Código do Ativo", "Ativo", "Codigo"],
    "isin":              ["ISIN", "Codigo ISIN"],
    "emissor_nome":      ["Empresa", "Emissor", "Nome do Emissor"],
    "emissor_cnpj":      ["CNPJ", "CNPJ do Emissor", "CNPJ Emissor"],
    "situacao":          ["Situacao", "Situação"],
    "data_emissao":      ["Data de Emissao", "Data de Emissão"],
    "data_vencimento":   ["Data de Vencimento"],
    "emissao":           ["Emissao", "Emissão", "Numero da Emissao"],
    "serie":             ["Serie", "Série"],
    "quantidade":        ["Quantidade Emitida", "Quantidade em Mercado", "Quantidade"],
    "valor_nominal":     ["Valor Nominal na Emissao", "Valor Nominal na Emissão", "Valor Nominal"],
    # o export do SND não tem volume (conferido em 2026-10-30): parse_snd calcula quantidade × valor nominal
    "valor_emissao":     ["Volume", "Valor Total Emitido", "Volume Emitido"],
    "indice":            ["Indice", "Índice", "Indexador", "Indice Correcao"],
    "percentual_indice": ["Percentual Multiplicador/Rentabilidade", "Percentual Multiplicador", "Percentual do Indice"],
    "juros":             ["Taxa de Juros", "Juros Criterio Novo - Taxa", "Spread"],
    "especie":           ["Especie", "Espécie", "Garantia/Especie", "Garantia"],
    "classe":            ["Classe"],
    "incentivada":       ["Deb. Incent. (Lei 12.431)", "Artigo 2 da Lei 12.431", "Lei 12.431", "Incentivada"],
    "agente_fiduciario": ["Agente Fiduciario", "Agente Fiduciário"],
}


def ler_tabela_texto(raw: bytes, marcador: str) -> pd.DataFrame:
    """Texto com linhas de título antes do cabeçalho: acha a primeira linha que contém `marcador` (normalizado)
    e lê dali, adivinhando o separador (tab, ';' ou '@')."""
    s = raw.decode("latin-1")
    linhas = s.splitlines()
    alvo = norm(marcador)
    for i, l in enumerate(linhas):
        if alvo in norm(l):
            sep = max(("\t", ";", "@"), key=l.count)
            corpo = "\n".join(linhas[i:])
            return pd.read_csv(io.StringIO(corpo), sep=sep, dtype=str, keep_default_na=False,
                               on_bad_lines="skip", engine="python")
    raise ColunaAusente(f"cabeçalho com '{marcador}' não encontrado; início do arquivo: {s[:300]!r}")


def parse_snd(raw: bytes) -> list[dict]:
    """Export de características do SND → linhas de rf_ativos (tipo DEB)."""
    df = ler_tabela_texto(raw, "Codigo do Ativo")
    df.columns = [str(c).strip() for c in df.columns]
    mapa = achar_colunas(list(df.columns), APELIDOS_SND, obrigatorias=("codigo",))
    hoje = date.today().isoformat()
    out = []
    for r in df.to_dict("records"):
        codigo = (texto(_valor(r, mapa, "codigo")) or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{4,12}", codigo):
            continue
        indice = texto(_valor(r, mapa, "indice"))
        pct = texto(_valor(r, mapa, "percentual_indice"))
        juros = texto(_valor(r, mapa, "juros"))
        partes = [p for p in (f"{pct}% do {indice}" if pct and indice and indice.upper() != "PRE" else None,
                              indice if indice and not pct else None,
                              f"+ {juros}%" if juros else None) if p]
        inc = norm(_valor(r, mapa, "incentivada"))
        qtd, vn = num_br(_valor(r, mapa, "quantidade")), num_br(_valor(r, mapa, "valor_nominal"))
        volume = num_br(_valor(r, mapa, "valor_emissao")) or (qtd * vn if qtd and vn else None)
        out.append({
            "codigo":            codigo,
            "isin":              texto(_valor(r, mapa, "isin")),
            "tipo":              "DEB",
            "emissor_cnpj":      fmt_cnpj(_valor(r, mapa, "emissor_cnpj")),
            "emissor_nome":      texto(_valor(r, mapa, "emissor_nome")),
            "emissao":           texto(_valor(r, mapa, "emissao")),
            "serie":             texto(_valor(r, mapa, "serie")),
            "data_emissao":      data_br(_valor(r, mapa, "data_emissao")),
            "data_vencimento":   data_br(_valor(r, mapa, "data_vencimento")),
            "valor_emissao":     volume,
            "quantidade":        qtd,
            "valor_nominal":     vn,
            "indexador":         indexador_de(indice),
            "remuneracao":       " ".join(partes) or None,
            "especie_garantia":  texto(_valor(r, mapa, "especie")),
            "incentivada_12431": 1 if inc.startswith(("s", "1")) else (0 if inc else None),
            "agente_fiduciario": texto(_valor(r, mapa, "agente_fiduciario")),
            "situacao":          texto(_valor(r, mapa, "situacao")),
            "fonte":             "snd",
            "atualizado_em":     hoje,
        })
    return out


# ── CVM: ofertas registradas ─────────────────────────────────────────────────

APELIDOS_CVM_OFERTA = {
    "numero_registro":   ["Numero_Registro_Oferta", "Numero_Requerimento", "Numero_Processo", "Numero_Registro"],
    "tipo_ativo":        ["Tipo_Ativo", "Valor_Mobiliario", "Tipo_Valor_Mobiliario"],
    "codigo":            ["Cod_Negociacao", "Codigo_Negociacao", "Codigo_Ativo", "Cod_Ativo"],
    "isin":              ["Cod_ISIN", "Codigo_ISIN", "ISIN"],
    "emissor_cnpj":      ["CNPJ_Emissor", "CNPJ_Securitizadora", "CNPJ_Companhia"],
    "emissor_nome":      ["Nome_Emissor", "Nome_Securitizadora", "Nome_Companhia"],
    "devedor_cnpj":      ["CNPJ_Devedor", "CPF_CNPJ_Devedor", "CNPJ_Cedente", "CNPJ_Originador"],
    "devedor_nome":      ["Nome_Devedor", "Devedor", "Nome_Cedente", "Nome_Originador"],
    "emissao":           ["Emissao", "Numero_Emissao"],
    "serie":             ["Serie", "Numero_Serie"],
    "data_registro":     ["Data_Registro_Oferta", "Data_Registro", "Data_Requerimento", "Data_Protocolo"],
    "data_emissao":      ["Data_Emissao"],
    "data_vencimento":   ["Data_Vencimento"],
    "valor_total":       ["Valor_Total", "Valor_Total_Registrado", "Valor_Total_Emissao"],
    "quantidade":        ["Quantidade_Total", "Qtd_Total_Registrada", "Quantidade_Total_Registrada"],
    "taxa_juros":        ["Taxa_Juros", "Remuneracao", "Juros"],
    "atualizacao":       ["Atualizacao_Monetaria", "Indexador"],
    "rito":              ["Rito_Oferta", "Rito_Requerimento", "Tipo_Oferta", "Modalidade_Oferta"],
    "publico_alvo":      ["Publico_Alvo", "Tipo_Investidor"],
    "lider_nome":        ["Nome_Lider", "Nome_Coordenador_Lider", "Lider"],
    "incentivada":       ["Oferta_Incentivo_Fiscal", "Titulo_Incentivado", "Incentivo_Fiscal"],
    # só na Resolução 160
    "status":            ["Status_Requerimento"],
    "tipo_lastro":       ["Tipo_lastro"],
    "descricao_garantias": ["Descricao_garantias"],
    "descricao_lastro":  ["Descricao_lastro"],
    "devedores":         ["Identificacao_devedores_coobrigados"],
    "agente_fiduciario": ["Agente_fiduciario"],
    "avaliador_risco":   ["Avaliador_Risco"],
}


def ler_zip_csvs(raw: bytes) -> dict[str, pd.DataFrame]:
    """Todos os CSVs de um ZIP da CVM (';', latin-1), por nome de arquivo."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for nome in z.namelist():
            if not nome.lower().endswith(".csv") or ".." in nome or nome.startswith("/"):
                continue
            with z.open(nome) as f:
                out[nome] = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str, keep_default_na=False)
    return out


def parse_cvm_ofertas(df: pd.DataFrame, fonte: str) -> list[dict]:
    """CSV de ofertas da CVM → linhas de rf_ofertas, só de títulos de dívida (debêntures, CRI, CRA)."""
    mapa = achar_colunas(list(df.columns), APELIDOS_CVM_OFERTA, obrigatorias=("tipo_ativo", "emissor_cnpj"))
    out = []
    for r in df.to_dict("records"):
        tipo_ativo = texto(_valor(r, mapa, "tipo_ativo"))
        if tipo_por_descricao(tipo_ativo) == "OUTRO":
            continue
        juros = texto(_valor(r, mapa, "taxa_juros"))
        atual = texto(_valor(r, mapa, "atualizacao"))
        devedores = texto(_valor(r, mapa, "devedores"))
        devedor_cnpj = fmt_cnpj(_valor(r, mapa, "devedor_cnpj"))
        if not devedor_cnpj and devedores:
            # texto livre ("Raízen S.A., CNPJ 33.453.598/0001-23"): só usa o CNPJ se houver um único
            achados = {fmt_cnpj(m) for m in re.findall(r"\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}", devedores)}
            achados.discard(None)
            devedor_cnpj = achados.pop() if len(achados) == 1 else None
        linha = {
            "fonte":             fonte,
            "numero_registro":   texto(_valor(r, mapa, "numero_registro")),
            "codigo":            (texto(_valor(r, mapa, "codigo")) or "").upper() or None,
            "isin":              texto(_valor(r, mapa, "isin")),
            "tipo_ativo":        tipo_ativo,
            "emissor_cnpj":      fmt_cnpj(_valor(r, mapa, "emissor_cnpj")),
            "emissor_nome":      texto(_valor(r, mapa, "emissor_nome")),
            "devedor_cnpj":      devedor_cnpj,
            "devedor_nome":      texto(_valor(r, mapa, "devedor_nome")) or nome_antes_do_cnpj(devedores, devedor_cnpj),
            "emissao":           texto(_valor(r, mapa, "emissao")),
            "serie":             texto(_valor(r, mapa, "serie")),
            "data_registro":     data_br(_valor(r, mapa, "data_registro")),
            "data_emissao":      data_br(_valor(r, mapa, "data_emissao")),
            "data_vencimento":   data_br(_valor(r, mapa, "data_vencimento")),
            "valor_total":       num_br(_valor(r, mapa, "valor_total")),
            "quantidade":        num_br(_valor(r, mapa, "quantidade")),
            "remuneracao":       " ".join(p for p in (atual, juros) if p) or None,
            "rito":              texto(_valor(r, mapa, "rito")),
            "publico_alvo":      texto(_valor(r, mapa, "publico_alvo")),
            "lider_nome":        texto(_valor(r, mapa, "lider_nome")),
            "incentivada_12431": _sim_nao(_valor(r, mapa, "incentivada")),
            "status":            texto(_valor(r, mapa, "status")),
            "tipo_lastro":       texto(_valor(r, mapa, "tipo_lastro")),
            "descricao_garantias": texto(_valor(r, mapa, "descricao_garantias")),
            "descricao_lastro":  texto(_valor(r, mapa, "descricao_lastro")),
            "devedores_coobrigados": devedores,
            "agente_fiduciario": texto(_valor(r, mapa, "agente_fiduciario")),
            "avaliador_risco":   texto(_valor(r, mapa, "avaliador_risco")),
        }
        linha["chave"] = "|".join(str(linha[k] or "") for k in (
            "fonte", "numero_registro", "emissor_cnpj", "emissao", "serie", "isin", "codigo", "data_registro"))
        out.append(linha)
    return out


def _sim_nao(v) -> int | None:
    n = norm(v)
    if not n:
        return None
    return 1 if n.startswith(("s", "1")) else 0


# ── ANBIMA: taxas indicativas ────────────────────────────────────────────────

APELIDOS_ANBIMA = {
    "codigo":          ["Codigo", "Código", "Codigo do Ativo"],
    "nome":            ["Nome", "Emissor"],
    "vencimento":      ["Repac Venc", "Vencimento", "Repac. Venc."],
    "indice":          ["Indice Correcao", "Índice/ Correção", "Indice", "Indexador", "Remuneracao"],
    "taxa_compra":     ["Taxa de Compra"],
    "taxa_venda":      ["Taxa de Venda"],
    "taxa_indicativa": ["Taxa Indicativa"],
    "desvio_padrao":   ["Desvio Padrao", "Desvio Padrão"],
    "intervalo_min":   ["Intervalo Indicativo Minimo", "Intervalo Mínimo", "Intervalo Indicativo Min"],
    "intervalo_max":   ["Intervalo Indicativo Maximo", "Intervalo Máximo", "Intervalo Indicativo Max"],
    "pu":              ["PU"],
    "pct_pu_par":      ["% PU Par", "PU Par", "Percentual PU Par"],
    "duration":        ["Duration"],
    "referencia":      ["Referencia NTN-B", "Referência NTN-B", "Referencia"],
}


def url_anbima(tipo: str, dia: date) -> str:
    modelo = URL_ANBIMA_DEB if tipo == "DEB" else URL_ANBIMA_CRI_CRA
    return modelo.format(aammdd=dia.strftime("%y%m%d"))


def parse_anbima(raw: bytes, dia: date, tipo_padrao: str) -> list[dict]:
    """Arquivo diário da ANBIMA → linhas de rf_taxas.

    O arquivo tem blocos (um por indexador), cada um com o próprio cabeçalho começando em 'Código'; o separador
    é '@' (aceita também ';' e tab). Linhas de título, totais e notas entre os blocos são ignoradas."""
    s = raw.decode("latin-1")
    out, mapa, sep, cab = [], None, None, None
    for l in s.splitlines():
        if not l.strip():
            continue
        n = norm(l)
        if n.startswith("codigo") and ("taxa" in n or "pu" in n):
            sep = max(("@", ";", "\t"), key=l.count)
            cab = [c.strip() for c in l.split(sep)]
            mapa = achar_colunas(cab, APELIDOS_ANBIMA, obrigatorias=("codigo", "taxa_indicativa"))
            continue
        if not mapa or sep not in l:
            continue
        r = dict(zip(cab, [c.strip() for c in l.split(sep)]))
        codigo = (texto(_valor(r, mapa, "codigo")) or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{4,14}", codigo):
            continue
        tipo = tipo_por_codigo(codigo)
        out.append({
            "codigo":          codigo,
            "data":            dia.isoformat(),
            "tipo":            tipo if tipo != "OUTRO" else tipo_padrao,
            "indice":          texto(_valor(r, mapa, "indice")),
            "taxa_compra":     num_br(_valor(r, mapa, "taxa_compra")),
            "taxa_venda":      num_br(_valor(r, mapa, "taxa_venda")),
            "taxa_indicativa": num_br(_valor(r, mapa, "taxa_indicativa")),
            "desvio_padrao":   num_br(_valor(r, mapa, "desvio_padrao")),
            "intervalo_min":   num_br(_valor(r, mapa, "intervalo_min")),
            "intervalo_max":   num_br(_valor(r, mapa, "intervalo_max")),
            "pu":              num_br(_valor(r, mapa, "pu")),
            "pct_pu_par":      num_br(_valor(r, mapa, "pct_pu_par")),
            "duration_du":     num_br(_valor(r, mapa, "duration")),
            "referencia":      texto(_valor(r, mapa, "referencia")),
        })
    return out


# ── ANBIMA Data: dataset "CRIs e CRAs - Precificação ANBIMA" (download manual) ──

APELIDOS_ANBIMA_DATA = {
    "data":            ["Data de referencia"],
    "tipo":            ["Tipo"],
    "codigo":          ["Codigo"],
    "emissor":         ["Emissor"],
    "devedor":         ["Devedor"],
    "tipo_remuneracao": ["Tipo de remuneracao"],
    "taxa_correcao":   ["Taxa de correcao"],
    "serie":           ["Serie"],
    "emissao":         ["Emissao"],
    "vencimento":      ["Data de vencimento"],
    "taxa_compra":     ["Taxa de compra"],
    "taxa_venda":      ["Taxa de venda"],
    "taxa_indicativa": ["Taxa indicativa"],
    "pu":              ["PU Indicativo"],
    "desvio_padrao":   ["Desvio padrao"],
    "duration":        ["Duration (dias uteis)", "Duration"],
    "pct_pu_par":      ["% PU par"],
    "referencia":      ["Referencia NTN-B"],
}


def _num_xls(v) -> float | None:
    """Célula numérica do Excel (float) ou texto brasileiro."""
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    return num_br(v)


def _pct(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def remuneracao_anbima(tipo: str | None, taxa: float | None) -> str | None:
    """('IPCA', 6.7825) → 'IPCA + 6,7825%'; ('DI MULTIPLICATIVO', 101.5) → '101,5% do DI'; no formato do SND."""
    n = norm(tipo)
    if not n:
        return None
    if taxa is None:
        return tipo
    if "multiplicativo" in n:
        return f"{_pct(taxa)}% do DI"
    if "pre" in n:
        return f"{_pct(taxa)}%"
    rotulo = "DI" if n.startswith("di") else (tipo or "").strip()
    return f"{rotulo} + {_pct(taxa)}%"


def parse_anbima_data_cri_cra(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Planilha do dataset (uma linha por título × dia, últimos cinco dias úteis do mercado inteiro) →
    (linhas de rf_taxas, cadastro por código para rf_ativos, do dia mais recente)."""
    mapa = achar_colunas([str(c) for c in df.columns], APELIDOS_ANBIMA_DATA,
                         obrigatorias=("data", "codigo", "taxa_indicativa"))
    taxas, cadastro = [], {}
    for r in df.to_dict("records"):
        codigo = (texto(_valor(r, mapa, "codigo")) or "").upper()
        dia = data_br(_valor(r, mapa, "data"))
        if not (re.fullmatch(r"[A-Z0-9]{6,14}", codigo) and dia):
            continue
        tipo = (texto(_valor(r, mapa, "tipo")) or tipo_por_codigo(codigo)).upper()
        remun = remuneracao_anbima(texto(_valor(r, mapa, "tipo_remuneracao")), _num_xls(_valor(r, mapa, "taxa_correcao")))
        taxas.append({
            "codigo": codigo, "data": dia, "tipo": tipo, "indice": remun,
            "taxa_compra":     _num_xls(_valor(r, mapa, "taxa_compra")),
            "taxa_venda":      _num_xls(_valor(r, mapa, "taxa_venda")),
            "taxa_indicativa": _num_xls(_valor(r, mapa, "taxa_indicativa")),
            "desvio_padrao":   _num_xls(_valor(r, mapa, "desvio_padrao")),
            "pu":              _num_xls(_valor(r, mapa, "pu")),
            "pct_pu_par":      _num_xls(_valor(r, mapa, "pct_pu_par")),
            "duration_du":     _num_xls(_valor(r, mapa, "duration")),
            "referencia":      texto(_valor(r, mapa, "referencia")),   # '15/05/2037', como no arquivo de debêntures
        })
        ant = cadastro.get(codigo)
        if ant and ant["_dia"] >= dia:
            continue

        def inteiro(v):
            x = _num_xls(v)
            return str(int(x)) if x is not None else texto(v)
        cadastro[codigo] = {
            "_dia": dia, "codigo": codigo, "tipo": tipo,
            "emissor_nome": texto(_valor(r, mapa, "emissor")), "devedor_nome": texto(_valor(r, mapa, "devedor")),
            "emissao": inteiro(_valor(r, mapa, "emissao")), "serie": inteiro(_valor(r, mapa, "serie")),
            "data_vencimento": data_br(_valor(r, mapa, "vencimento")),
            "indexador": indexador_de(remun), "remuneracao": remun,
        }
    return [t for t in taxas if t["taxa_indicativa"] is not None or t["pu"] is not None], \
        [{k: v for k, v in c.items() if k != "_dia"} for c in cadastro.values()]


def ler_anbima_data_cri_cra(caminho) -> tuple[list[dict], list[dict]]:
    """O arquivo vem com extensão .xls, mas é .xlsx (OOXML)."""
    return parse_anbima_data_cri_cra(pd.read_excel(caminho, engine="openpyxl"))


# ── Verificação ──────────────────────────────────────────────────────────────

def _baixar(url: str) -> bytes:
    import httpx
    r = httpx.get(url, headers=HEADERS, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _relatorio(nome: str, url: str, linhas: list[dict], campos: list[str]):
    print(f"\n== {nome}\n   {url}\n   linhas lidas: {len(linhas)}")
    if not linhas:
        print("   AVISO: nenhuma linha; confira o layout")
        return
    for c in campos:
        n = sum(1 for l in linhas if l.get(c) not in (None, ""))
        print(f"   {c:<20} {n:>7} preenchidas ({100 * n / len(linhas):.0f}%)")


def verificar() -> int:
    """Baixa uma amostra de cada fonte e mostra o que cada campo canônico encontrou. 0 = todas leram algo."""
    from datetime import timedelta
    falhas = 0
    try:
        raw = _baixar(URL_SND_CARACTERISTICAS)
        print(f"\n   SND colunas: {list(ler_tabela_texto(raw, 'Codigo do Ativo').columns)}")
        linhas = parse_snd(raw)
        _relatorio("SND características", URL_SND_CARACTERISTICAS, linhas,
                   ["isin", "emissor_cnpj", "data_vencimento", "valor_emissao", "remuneracao", "especie_garantia",
                    "incentivada_12431", "agente_fiduciario"])
        falhas += not linhas
    except Exception as e:
        print(f"\n== SND características: FALHOU ({e})")
        falhas += 1
    try:
        csvs = ler_zip_csvs(_baixar(URL_CVM_OFERTAS))
        for nome, df in csvs.items():
            print(f"\n   {nome}: {len(df)} linhas; colunas: {list(df.columns)}")
            try:
                linhas = parse_cvm_ofertas(df, nome)
                _relatorio(f"CVM ofertas · {nome}", URL_CVM_OFERTAS, linhas,
                           ["devedor_cnpj", "emissao", "serie", "data_registro", "valor_total", "remuneracao",
                            "descricao_garantias", "descricao_lastro", "devedores_coobrigados"])
            except ColunaAusente as e:
                print(f"   {nome}: ignorado ({e})")
    except Exception as e:
        print(f"\n== CVM ofertas: FALHOU ({e})")
        falhas += 1
    for tipo in ("DEB", "CRI_CRA"):
        if tipo == "CRI_CRA" and not URL_ANBIMA_CRI_CRA:
            print("\n== ANBIMA CRI_CRA: sem URL fixa; baixe o dataset no data.anbima.com.br e rode "
                  "ingest_rf_taxas.py --arquivo (ver comentário no topo do arquivo)")
            continue
        dia, lido = date.today(), False
        for _ in range(7):   # volta até achar um dia útil publicado
            dia -= timedelta(days=1)
            if dia.weekday() >= 5:
                continue
            url = url_anbima(tipo, dia)
            try:
                linhas = parse_anbima(_baixar(url), dia, "DEB" if tipo == "DEB" else "OUTRO")
            except Exception as e:
                print(f"\n   ANBIMA {tipo} {dia}: {e}")
                continue
            _relatorio(f"ANBIMA {tipo} {dia}", url, linhas,
                       ["indice", "taxa_indicativa", "pu", "pct_pu_par", "duration_du", "referencia"])
            lido = bool(linhas)
            break
        falhas += not lido
    print(f"\n{falhas} fonte(s) sem leitura. Ajuste URL (RF_URL_*) ou apelidos neste arquivo.")
    return 1 if falhas else 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verificar", action="store_true", help="baixa uma amostra de cada fonte e mostra os campos lidos")
    a = p.parse_args()
    if a.verificar:
        sys.exit(verificar())
    p.print_help()
