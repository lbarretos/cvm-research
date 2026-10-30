"""
Cadastro de renda fixa: características das debêntures (SND) e ofertas registradas na CVM.

Grava rf_ativos (um título por código), rf_ofertas e as partes publicadas em campo (rf_partes com
fonte 'cadastro'). Cobre o mercado inteiro, não só o watchlist: o volume é pequeno (dezenas de
milhares de linhas) e permite comparar títulos entre si.

Precedência em rf_ativos: o SND descreve a debênture com mais campos; a oferta da CVM só cria o
título quando ele não está no SND (CRI e CRA) e só completa campos vazios (devedor, ISIN).

Uso:
  python ingest_rf_cadastro.py              # SND + CVM
  python ingest_rf_cadastro.py --so-snd
  python ingest_rf_cadastro.py --so-cvm
Layouts: ver rf_fontes.py (`--verificar`).
"""
import argparse
import sys

import rf_fontes as F
from utils import _http_get, get_db, upsert


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


def ativos_de_ofertas(ofertas: list[dict], ja_existem: set[str]) -> list[dict]:
    """Títulos com código informado pela CVM e ausentes do SND (na prática, CRI e CRA)."""
    out = {}
    for o in ofertas:
        cod = o.get("codigo")
        if not cod or cod in ja_existem:
            continue
        tipo = F.tipo_por_descricao(o["tipo_ativo"])
        out[cod] = {
            "codigo": cod, "isin": o["isin"], "tipo": tipo,
            "emissor_cnpj": o["emissor_cnpj"], "emissor_nome": o["emissor_nome"],
            "devedor_cnpj": o["devedor_cnpj"], "devedor_nome": o["devedor_nome"],
            "emissao": o["emissao"], "serie": o["serie"],
            "data_emissao": o["data_emissao"], "data_vencimento": o["data_vencimento"],
            "valor_emissao": o["valor_total"], "quantidade": o["quantidade"],
            "valor_nominal": (o["valor_total"] / o["quantidade"]) if o["valor_total"] and o["quantidade"] else None,
            "indexador": F.indexador_de(o["remuneracao"]), "remuneracao": o["remuneracao"],
            "especie_garantia": None, "incentivada_12431": o["incentivada_12431"],
            "agente_fiduciario": None, "situacao": None, "fonte": "cvm_oferta",
            "atualizado_em": o["data_registro"],
        }
    return list(out.values())


def completar_com_ofertas(conn, ofertas: list[dict]) -> int:
    """Preenche devedor e ISIN vazios em rf_ativos casando a oferta por código ou por emissor + emissão + série."""
    n = 0
    for o in ofertas:
        if not (o.get("devedor_cnpj") or o.get("isin")):
            continue
        if o.get("codigo"):
            where, args = "codigo = ?", [o["codigo"]]
        elif o.get("emissor_cnpj") and o.get("emissao") and o.get("serie"):
            where, args = "emissor_cnpj = ? AND emissao = ? AND serie = ?", [o["emissor_cnpj"], o["emissao"], o["serie"]]
        else:
            continue
        cur = conn.execute(
            "UPDATE rf_ativos SET devedor_cnpj = COALESCE(devedor_cnpj, ?), devedor_nome = COALESCE(devedor_nome, ?), "
            f"isin = COALESCE(isin, ?) WHERE {where}", [o["devedor_cnpj"], o["devedor_nome"], o["isin"], *args])
        n += cur.rowcount
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
            no_snd = {r[0] for r in conn.execute("SELECT codigo FROM rf_ativos WHERE fonte = 'snd'")}
            upsert(conn, "rf_ativos", ativos_de_ofertas(ofertas, no_snd), conflict="codigo")
            print(f"  rf_ativos completados pela CVM: {completar_com_ofertas(conn, ofertas)}")
        except Exception as e:
            print(f"ERRO CVM ofertas: {e}", file=sys.stderr)
            falhas += 1

    upsert(conn, "rf_partes", partes_de_cadastro(conn), conflict="chave")
    if falhas == (1 if (a.so_snd or a.so_cvm) else 2):
        sys.exit(1)   # nenhuma fonte leu: o job semanal registra a falha


if __name__ == "__main__":
    main()
