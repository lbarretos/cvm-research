"""
Cadastro de renda fixa: características das debêntures (SND) e ofertas registradas na CVM.

Grava rf_ativos (um título por código), rf_ofertas e as partes publicadas em campo (rf_partes com
fonte 'cadastro'). Cobre o mercado inteiro, não só o watchlist: o volume é pequeno (dezenas de
milhares de linhas) e permite comparar títulos entre si.

Precedência em rf_ativos: o SND descreve a debênture com mais campos. A CVM não publica código de
negociação (conferido em 2026-10-30), então CRI e CRA entram por rf_watchlist.csv: código + CNPJ da
securitizadora + emissão (+ série), copiados da página do título na ANBIMA/B3 ou do termo. A oferta
casada por emissor + emissão completa campos vazios (devedor, datas, valor) e, na Resolução 160, traz a
descrição das garantias e do lastro, que passa pela mesma extração por regra dos PDFs (fonte 'cvm_oferta').

Uso:
  python ingest_rf_cadastro.py              # SND + CVM
  python ingest_rf_cadastro.py --so-snd
  python ingest_rf_cadastro.py --so-cvm
Layouts: ver rf_fontes.py (`--verificar`).
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import rf_fontes as F
from utils import _http_get, get_db, upsert

RF_WATCHLIST = Path(__file__).parents[2] / "rf_watchlist.csv"

# emissor + emissão (+ série quando as duas existem); CAST tira o 'ª' e os zeros à esquerda
SQL_OFERTAS_DO_ATIVO = """
    SELECT * FROM rf_ofertas
    WHERE emissor_cnpj = :emissor AND CAST(emissao AS INTEGER) = CAST(:emissao AS INTEGER)
      AND (serie IS NULL OR :serie IS NULL OR CAST(serie AS INTEGER) = CAST(:serie AS INTEGER))
    ORDER BY data_registro"""


def baixar_snd() -> list[dict]:
    print(f"Baixando {F.URL_SND_CARACTERISTICAS}...")
    return F.parse_snd(_http_get(F.URL_SND_CARACTERISTICAS, timeout=300).content)


def baixar_ofertas() -> list[dict]:
    print(f"Baixando {F.URL_CVM_OFERTAS}...")
    out = []
    for nome, df in F.ler_zip_csvs(_http_get(F.URL_CVM_OFERTAS, timeout=300).content).items():
        fonte = "cvm_160" if "160" in nome else "cvm_distrib"
        try:
            linhas = F.parse_cvm_ofertas(df, fonte)
        except F.ColunaAusente as e:
            # o ZIP traz CSVs auxiliares (ex.: listas de distribuidores) sem as colunas da oferta
            print(f"  {nome}: ignorado ({e})")
            continue
        print(f"  {nome}: {len(linhas)} ofertas de dívida")
        out += linhas
    return out


def ler_manuais(path: Path | None = None) -> list[dict]:
    """Linhas de rf_watchlist.csv com emissor_cnpj preenchido: o cadastro mínimo de quem não está no SND."""
    path = path or RF_WATCHLIST
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        linhas = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    out = []
    for r in csv.DictReader(linhas):
        cod = (r.get("codigo") or "").strip().upper()
        if cod and F.fmt_cnpj(r.get("emissor_cnpj")):
            out.append({"codigo": cod, "tipo": (r.get("tipo") or "").strip().upper() or F.tipo_por_codigo(cod),
                        "emissor_cnpj": F.fmt_cnpj(r["emissor_cnpj"]), "emissao": F.texto(r.get("emissao")),
                        "serie": F.texto(r.get("serie")), "isin": F.texto(r.get("isin"))})
    return out


def cadastrar_manuais(conn, manuais: list[dict]) -> int:
    """Cria em rf_ativos (fonte 'manual') os códigos da lista que nenhuma fonte trouxe. O SND sempre prevalece."""
    ja = {r[0] for r in conn.execute("SELECT codigo FROM rf_ativos WHERE fonte <> 'manual'")}
    linhas = [{**m, "fonte": "manual", "atualizado_em": date.today().isoformat()}
              for m in manuais if m["codigo"] not in ja]
    upsert(conn, "rf_ativos", linhas, conflict="codigo")
    return len(linhas)


def ofertas_do_ativo(conn, ativo: dict) -> list[dict]:
    if not (ativo.get("emissor_cnpj") and ativo.get("emissao")):
        return []
    cur = conn.execute(SQL_OFERTAS_DO_ATIVO, {"emissor": ativo["emissor_cnpj"], "emissao": ativo["emissao"],
                                               "serie": ativo.get("serie")})
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def completar_com_ofertas(conn) -> int:
    """Preenche campos vazios de rf_ativos com a oferta casada por emissor + emissão (+ série) e passa a descrição
    de garantias/lastro/devedores da Resolução 160 pela extração por regra (fonte 'cvm_oferta')."""
    import extrai_rf
    cols = ["codigo", "tipo", "emissor_cnpj", "emissao", "serie"]
    n = 0
    for r in conn.execute(f"SELECT {','.join(cols)} FROM rf_ativos WHERE emissao IS NOT NULL").fetchall():
        a = dict(zip(cols, r))
        ofs = ofertas_do_ativo(conn, a)
        if not ofs:
            continue
        o = ofs[-1]
        conn.execute(
            "UPDATE rf_ativos SET devedor_cnpj = COALESCE(devedor_cnpj, ?), devedor_nome = COALESCE(devedor_nome, ?), "
            "emissor_nome = COALESCE(emissor_nome, ?), data_emissao = COALESCE(data_emissao, ?), "
            "data_vencimento = COALESCE(data_vencimento, ?), valor_emissao = COALESCE(valor_emissao, ?), "
            "remuneracao = COALESCE(remuneracao, ?), incentivada_12431 = COALESCE(incentivada_12431, ?), "
            "agente_fiduciario = COALESCE(agente_fiduciario, ?) WHERE codigo = ?",
            (o["devedor_cnpj"], o["devedores_coobrigados"] if o["devedor_cnpj"] else None, o["emissor_nome"],
             o["data_emissao"], o["data_vencimento"], o["valor_total"], o["remuneracao"], o["incentivada_12431"],
             o["agente_fiduciario"], a["codigo"]))
        n += 1
        for o in ofs:
            partes = [("Garantias: ", o.get("descricao_garantias")), ("Lastro: ", o.get("descricao_lastro")),
                      ("Devedores e coobrigados: ", o.get("devedores_coobrigados"))]
            texto = " ".join(rot + t for rot, t in partes if t)
            if texto:
                extrai_rf.gravar(conn, f"oferta:{o['chave']}", a["codigo"], a["tipo"],
                                 extrai_rf.extrair(texto, a["tipo"]), fonte="cvm_oferta")
    conn.commit()
    return n


def partes_de_cadastro(conn, incluir_teste: bool = False) -> list[dict]:
    """Partes publicadas em campo: emissor (securitizadora no CRI/CRA), devedor e agente fiduciário."""
    out = []
    for cod, tipo, ecnpj, enome, dcnpj, dnome, agente in conn.execute(
            "SELECT codigo, tipo, emissor_cnpj, emissor_nome, devedor_cnpj, devedor_nome, agente_fiduciario "
            "FROM rf_ativos WHERE fonte <> 'teste' OR ?", (incluir_teste,)):
        if ecnpj or enome:
            out.append(parte(cod, "securitizadora" if tipo in ("CRI", "CRA") else "emissor", ecnpj, enome))
        if dcnpj or dnome:
            out.append(parte(cod, "devedor", dcnpj, dnome))
        if agente:
            out.append(parte(cod, "agente_fiduciario", None, agente))
    return out


def parte(codigo, papel, cnpj, nome, fonte="cadastro", doc_id=None, evidencia=None, confianca=1.0) -> dict:
    ident = F.cnpj_digitos(cnpj) or F.norm(nome)
    return {"chave": f"{codigo}|{papel}|{ident}|{fonte}", "codigo": codigo, "papel": papel,
            "cnpj": F.fmt_cnpj(cnpj), "nome": nome, "fonte": fonte, "doc_id": doc_id,
            "evidencia": evidencia, "confianca": confianca}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--so-snd", action="store_true")
    p.add_argument("--so-cvm", action="store_true")
    a = p.parse_args()
    conn = get_db()
    F.garantir_schema_rf(conn)
    falhas = 0

    if not a.so_cvm:
        try:
            upsert(conn, "rf_ativos", baixar_snd(), conflict="codigo")
        except Exception as e:
            print(f"ERRO SND: {e}", file=sys.stderr)
            falhas += 1

    if not a.so_snd:
        try:
            ofertas = baixar_ofertas()
            upsert(conn, "rf_ofertas", ofertas, conflict="chave")
        except Exception as e:
            print(f"ERRO CVM ofertas: {e}", file=sys.stderr)
            falhas += 1

    if falhas == (1 if (a.so_snd or a.so_cvm) else 2):
        sys.exit(1)   # nenhuma fonte leu: o job semanal registra a falha
    print(f"  rf_ativos da rf_watchlist.csv (sem SND): {cadastrar_manuais(conn, ler_manuais())}")
    print(f"  rf_ativos completados pela oferta CVM: {completar_com_ofertas(conn)}")

    upsert(conn, "rf_partes", partes_de_cadastro(conn), conflict="chave")


if __name__ == "__main__":
    main()
