"""
Documentos de um título de renda fixa (escritura, aditamentos, termo de securitização) → rf_docs,
com o texto do PDF, e em seguida a extração por regra (extrai_rf.py) de partes, garantias e lastro.

Sob demanda: só os códigos de rf_watchlist.csv (na raiz) ou os passados em --codigo, que entram na
lista e passam a ser atualizados pelo job semanal.

Onde procura:
- debênture: no IPE do emissor, documentos de escritura/debêntures; se a emissão é conhecida
  (rf_ativos.emissao), só os que citam o número dela no assunto.
- CRI/CRA: no IPE da securitizadora, documentos de securitização que citam a emissão e a série do
  título; sem emissão/série conhecidas a securitizadora tem centenas de documentos, então só lista
  os candidatos (--listar) e pede --protocolo, --url ou --arquivo.
- à mão: --url (link do PDF, ex.: o da aba de documentos do data.anbima.com.br) ou --arquivo (PDF já baixado).
  Um termo cobre várias séries: repita --codigo para ligá-lo a todas. O link pré-assinado do S3 que o
  data.anbima.com.br entrega expira em horas e carrega um token: o texto é lido na hora e o link é gravado
  sem a query string.
O IPE vem da tabela ipe_docs quando o CNPJ está no watchlist; senão do ZIP anual da CVM, filtrado
pelo CNPJ (sem gravar nada em ipe_docs).

Uso:
  python ingest_rf_docs.py                                   # todos de rf_watchlist.csv
  python ingest_rf_docs.py --codigo RUMOB6 --codigo ERDVB4
  python ingest_rf_docs.py --codigo CRA024004SB --listar     # mostra candidatos sem baixar
  python ingest_rf_docs.py --codigo CRA024004SB --url 'https://…/termo.pdf?X-Amz-…'
  python ingest_rf_docs.py --codigo CRA02300796 --arquivo ~/Downloads/termo.pdf
  python ingest_rf_docs.py --codigo CRA024004SB --protocolo 012345IPE…
"""
import argparse
import csv
import hashlib
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import rf_fontes as F
from utils import get_db

RF_WATCHLIST = Path(__file__).parents[2] / "rf_watchlist.csv"
DOMINIOS_PDF = ("cvm.gov.br", "b3.com.br", "bmfbovespa.com.br")
PISO_IPE = 2015   # ZIPs do IPE anteriores vêm sem protocolo (ver CLAUDE.md)


# ── Lista de acompanhamento ──────────────────────────────────────────────────

def ler_watchlist(path: Path = RF_WATCHLIST) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        linhas = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    return [r["codigo"].strip().upper() for r in csv.DictReader(linhas) if (r.get("codigo") or "").strip()]


def acrescentar_watchlist(codigos: list[str], path: Path = RF_WATCHLIST) -> None:
    atuais = set(ler_watchlist(path))
    novos = [c for c in codigos if c not in atuais]
    if not novos:
        return
    novo_arquivo = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        if novo_arquivo:
            f.write("codigo,tipo,emissor_cnpj,emissao,serie,isin,observacao\n")
        for c in novos:
            f.write(f"{c},,,,,,adicionado em {date.today().isoformat()}\n")
    print(f"  rf_watchlist.csv: +{', '.join(novos)}")


# ── Relevância de um documento do IPE para o título ──────────────────────────

_UNIDADES = ["", "primeir", "segund", "terceir", "quart", "quint", "sext", "setim", "oitav", "non"]
_DEZENAS = ["", "decim", "vigesim", "trigesim", "quadragesim", "quinquagesim"]
_NAO_DEPOIS_DE_DEZENA = "".join(rf"(?<!{d}a )(?<!{d}o )" for d in _DEZENAS[1:])


def _extenso(n: int) -> str | None:
    """16 → regex de 'decima sexta' / 'decimo sexto' (texto já sem acento); None fora de 1–59."""
    if not 1 <= n < 60:
        return None
    partes = [p + "[ao]" for p in (_DEZENAS[n // 10], _UNIDADES[n % 10]) if p]
    return (_NAO_DEPOIS_DE_DEZENA if n < 10 else "") + r"\b" + r"\s+".join(partes)


def _cita_numero(texto: str, numero: str | None, palavra: str) -> bool:
    """O texto (já normalizado) cita o número: '5ª emissao', '05a emissao', '1ª serie', 'decima sexta emissao',
    '16ª (decima sexta) emissao'."""
    n = re.sub(r"\D", "", str(numero or ""))
    if not n:
        return False
    entre = r"\s*(?:\([^)]{0,30}\)\s*)?"
    if re.search(rf"(?<!\d)0*{int(n)}\s*(?:a|o|ª|º)?\.?{entre}{palavra}", texto):
        return True
    ext = _extenso(int(n))
    return bool(ext and re.search(rf"{ext}{entre}{palavra}", texto))


def relevante(doc: dict, ativo: dict) -> str | None:
    """'certo' (cita a emissão/série), 'talvez' (tipo de documento certo, sem número) ou None."""
    t = F.norm(" ".join(str(doc.get(k) or "") for k in ("categoria", "tipo", "especie", "assunto")))
    codigo = ativo["codigo"].lower()
    if codigo in t:
        return "certo"
    if ativo["tipo"] == "DEB":
        if not ("escritura" in t or ("debentur" in t and ("emiss" in t or "aditamento" in t))):
            return None
        return "certo" if _cita_numero(t, ativo.get("emissao"), "emiss") else "talvez"
    if not ("securitiza" in t or "termo" in t or re.search(r"\bcr[ai]\b", t)):
        return None
    if _cita_numero(t, ativo.get("emissao"), "emiss") and (
            not ativo.get("serie") or _cita_numero(t, ativo.get("serie"), "serie")):
        return "certo"
    return "talvez"


# ── Busca no IPE ─────────────────────────────────────────────────────────────

_ZIPS: dict = {}


def _ipe_do_zip(cnpj: str, desde: int) -> list[dict]:
    import ingest_ipe
    out = []
    for ano in range(max(desde, PISO_IPE), date.today().year + 1):
        if ano not in _ZIPS:
            try:
                _ZIPS[ano] = ingest_ipe.download_year(ano)
            except Exception as e:
                print(f"  IPE {ano}: {e}", file=sys.stderr)
                _ZIPS[ano] = None
        if _ZIPS[ano] is not None:
            out += ingest_ipe.process(_ZIPS[ano], {cnpj})
    return out


def documentos_ipe(conn, ativo: dict) -> list[dict]:
    cnpj = ativo.get("emissor_cnpj")
    if not cnpj:
        return []
    cols = ["protocolo_entrega", "categoria", "tipo", "especie", "assunto", "data_entrega", "link_download",
            "texto_extraido"]
    docs = [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {','.join(cols)} FROM ipe_docs WHERE cnpj_companhia = ?", (cnpj,))]
    if not docs:
        desde = int((ativo.get("data_emissao") or str(PISO_IPE))[:4]) - 1
        docs = _ipe_do_zip(cnpj, desde)
    return docs


def _abertura_cita_emissao(texto: str | None, ativo: dict) -> bool:
    """A capa do documento (primeiros 1.500 caracteres) cita a emissão — e a série, no CRI/CRA, quando conhecida."""
    if not texto:
        return False
    t = F.norm(texto[:1500])
    if not _cita_numero(t, ativo.get("emissao"), "emiss"):
        return False
    return ativo["tipo"] == "DEB" or not ativo.get("serie") or _cita_numero(t, ativo.get("serie"), "serie")


def candidatos(conn, ativo: dict) -> tuple[list[dict], list[dict]]:
    """(certos, talvez) entre os documentos do IPE do emissor/securitizadora."""
    certos, talvez = [], []
    for d in documentos_ipe(conn, ativo):
        r = relevante(d, ativo)
        if r == "talvez" and _abertura_cita_emissao(d.get("texto_extraido"), ativo):
            r = "certo"   # assunto genérico ("Emissão de Valores Mobiliários"), mas a capa diz qual emissão
        (certos if r == "certo" else talvez if r == "talvez" else []).append(d)
    return certos, talvez


# ── Gravação ─────────────────────────────────────────────────────────────────

def sem_query(url: str) -> str:
    """Link sem a query string: o pré-assinado do S3 traz um token de acesso que não pode ir para o banco."""
    return url.split("?", 1)[0]


def ligar_doc(conn, codigo: str, doc: dict, origem: str, cnpj: str | None) -> str:
    doc_id = doc.get("doc_id") or doc.get("protocolo_entrega") or \
        "url:" + hashlib.sha256(doc["link_download"].encode()).hexdigest()
    conn.execute(
        "INSERT INTO rf_docs (doc_id, origem, cnpj_remetente, categoria, tipo, especie, assunto, data_entrega, "
        "link_download, texto_extraido, chars_extraidos, extraido_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (doc_id) DO UPDATE SET texto_extraido = COALESCE(rf_docs.texto_extraido, excluded.texto_extraido),"
        " chars_extraidos = COALESCE(rf_docs.chars_extraidos, excluded.chars_extraidos)",
        (doc_id, origem, cnpj, doc.get("categoria"), doc.get("tipo"), doc.get("especie"), doc.get("assunto"),
         doc.get("data_entrega"), doc.get("link_download"), doc.get("texto_extraido"),
         len(doc["texto_extraido"]) if doc.get("texto_extraido") else None,
         datetime.now(timezone.utc).isoformat(timespec="seconds") if doc.get("texto_extraido") else None))
    conn.execute("INSERT OR IGNORE INTO rf_doc_ativo (doc_id, codigo) VALUES (?, ?)", (doc_id, codigo))
    return doc_id


def extrair_textos(conn, codigos: list[str], limite: int) -> int:
    from extract_pdf import fetch_pdf_text
    pend = conn.execute(
        "SELECT DISTINCT d.doc_id, d.link_download FROM rf_docs d JOIN rf_doc_ativo x USING (doc_id) "
        f"WHERE x.codigo IN ({','.join('?' * len(codigos))}) AND d.texto_extraido IS NULL "
        "AND d.extracao_falhou = 0 AND d.link_download IS NOT NULL LIMIT ?", [*codigos, limite]).fetchall()
    for doc_id, link in pend:
        print(f"  PDF {doc_id}")
        txt = fetch_pdf_text(link, DOMINIOS_PDF)
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if txt:
            conn.execute("UPDATE rf_docs SET texto_extraido = ?, chars_extraidos = ?, extraido_em = ?, "
                         "regras_em = NULL WHERE doc_id = ?", (txt, len(txt), agora, doc_id))
        else:
            conn.execute("UPDATE rf_docs SET extracao_falhou = 1 WHERE doc_id = ?", (doc_id,))
        conn.commit()
        time.sleep(0.5)   # o portal da CVM limita a taxa (ver ingest_notas_explicativas.py)
    return len(pend)


def rebuild_fts(conn) -> None:
    conn.execute("INSERT INTO rf_docs_fts(rf_docs_fts) VALUES ('rebuild')")
    conn.commit()


def ativo_de(conn, codigo: str) -> dict:
    cols = ["codigo", "tipo", "emissor_cnpj", "emissor_nome", "emissao", "serie", "data_emissao"]
    r = conn.execute(f"SELECT {','.join(cols)} FROM rf_ativos WHERE codigo = ?", (codigo,)).fetchone()
    if r:
        return dict(zip(cols, r))
    return {"codigo": codigo, "tipo": F.tipo_por_codigo(codigo), "emissor_cnpj": None, "emissor_nome": None,
            "emissao": None, "serie": None, "data_emissao": None}


def processar_codigo(conn, codigo: str, listar: bool = False) -> int:
    ativo = ativo_de(conn, codigo)
    if not ativo["emissor_cnpj"]:
        print(f"{codigo}: sem emissor em rf_ativos. Debênture: rode ingest_rf_cadastro.py. CRI/CRA: preencha "
              "emissor_cnpj, emissao e serie em rf_watchlist.csv e rode ingest_rf_cadastro.py; ou passe --url/--protocolo")
        return 0
    certos, talvez = candidatos(conn, ativo)
    print(f"{codigo} ({ativo['tipo']}, {ativo['emissor_nome']}): {len(certos)} documento(s) da emissão, "
          f"{len(talvez)} candidato(s) sem número")
    usar = certos or (talvez if ativo["tipo"] == "DEB" and len(talvez) <= 10 else [])
    if listar or (not usar and talvez):
        for d in sorted(certos + talvez, key=lambda d: d.get("data_entrega") or "", reverse=True)[:40]:
            marca = "*" if d in certos else " "
            print(f"   {marca} {d['protocolo_entrega']}  {d.get('data_entrega')}  {d.get('tipo')} · {d.get('assunto')}")
        if not usar:
            print("   nenhum documento cita a emissão: escolha um e rode com --protocolo, ou passe --url")
    if listar:
        return 0
    for d in usar:
        ligar_doc(conn, codigo, d, "ipe", ativo["emissor_cnpj"])
    conn.commit()
    return len(usar)


def doc_manual(url: str | None = None, arquivo: str | None = None) -> dict | None:
    """PDF passado à mão → registro de rf_docs com o texto já lido. Link gravado sem token; arquivo pelo hash."""
    from extract_pdf import fetch_pdf_text, pdf_bytes_text
    agora = date.today().isoformat()
    if url:
        if "X-Amz-" in url or "Signature=" in url:
            print("  link pré-assinado: lendo agora (expira); grava-se sem o token")
        texto = fetch_pdf_text(url, dominios=None)
        limpo = sem_query(url)
        return texto and {"doc_id": "url:" + hashlib.sha256(limpo.encode()).hexdigest(), "link_download": limpo,
                          "tipo": "manual", "assunto": Path(limpo).name, "data_entrega": agora,
                          "texto_extraido": texto}
    conteudo = Path(arquivo).expanduser().read_bytes()
    texto = pdf_bytes_text(conteudo)
    return texto and {"doc_id": "arquivo:" + hashlib.sha256(conteudo).hexdigest(), "link_download": None,
                      "tipo": "manual", "assunto": Path(arquivo).name, "data_entrega": agora,
                      "texto_extraido": texto}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--codigo", action="append", default=[], help="código do título (repetível)")
    p.add_argument("--url", help="link direto do PDF; lido na hora (liga a todos os --codigo)")
    p.add_argument("--arquivo", help="PDF local (liga a todos os --codigo)")
    p.add_argument("--protocolo", help="protocolo do IPE (liga a todos os --codigo)")
    p.add_argument("--listar", action="store_true", help="só mostra os documentos candidatos")
    p.add_argument("--limite", type=int, default=50, help="PDFs a baixar nesta execução (padrão 50)")
    a = p.parse_args()

    codigos = [c.strip().upper() for c in a.codigo] or ler_watchlist()
    if not codigos:
        print("nenhum código: passe --codigo ou preencha rf_watchlist.csv")
        return
    if (a.url or a.arquivo or a.protocolo) and not a.codigo:
        sys.exit("--url, --arquivo e --protocolo pedem --codigo")
    conn = get_db()
    F.garantir_schema_rf(conn)
    if a.codigo and not a.listar:
        acrescentar_watchlist(codigos)

    if a.url or a.arquivo:
        doc = doc_manual(url=a.url, arquivo=a.arquivo)
        if not doc:
            sys.exit("não consegui ler o PDF (link expirado? arquivo não é PDF?)")
        for c in codigos:
            ligar_doc(conn, c, doc, "url" if a.url else "arquivo", None)
        conn.commit()
    elif a.protocolo:
        cols = ["protocolo_entrega", "cnpj_companhia", "categoria", "tipo", "especie", "assunto", "data_entrega",
                "link_download", "texto_extraido"]
        r = conn.execute(f"SELECT {','.join(cols)} FROM ipe_docs WHERE protocolo_entrega = ?", (a.protocolo,)).fetchone()
        if not r:
            ativo = ativo_de(conn, codigos[0])
            achados = [d for d in documentos_ipe(conn, ativo) if d["protocolo_entrega"] == a.protocolo]
            if not achados:
                sys.exit(f"protocolo {a.protocolo} não encontrado no IPE do emissor")
            d = achados[0]
        else:
            d = dict(zip(cols, r))
        for c in codigos:
            ligar_doc(conn, c, d, "ipe", d.get("cnpj_companhia"))
        conn.commit()
    else:
        for c in codigos:
            try:
                processar_codigo(conn, c, a.listar)
            except Exception as e:
                print(f"{c}: ERRO {e}", file=sys.stderr)
    if a.listar:
        return

    n = extrair_textos(conn, codigos, a.limite)
    print(f"{n} PDF(s) processado(s)")
    rebuild_fts(conn)
    import extrai_rf
    for c in codigos:
        extrai_rf.processar(conn, c)


if __name__ == "__main__":
    main()
