"""
Cadeia de controle das partes dos títulos de renda fixa → rf_grupo (reconstruída inteira a cada execução).

Para cada CNPJ que aparece num título (emissor, securitizadora, devedor, fiador, garantidor…) e tem FRE
na base, sobe pelos acionistas controladores (acionista_controlador = 'S') do FRE mais recente:
1. controladores diretos (id_acionista_relacionado NULL) = nível 1;
2. quem controla cada holding dentro do mesmo FRE (id_acionista_relacionado = id do controlador) = nível + 1;
3. se o controlador também é companhia da base, continua pelo FRE dele (Rumo → Cosan → …).
Para em ciclo e em MAX_NIVEL. Um controlador sem FRE na base (fechado, pessoa física) é o último nível.

"Ativos do mesmo grupo" = títulos cujas partes compartilham algum controlador_doc (ver a skill).

Uso:
  python rf_grupo.py
"""

import rf_fontes as F
from utils import get_db

MAX_NIVEL = 8


def _doc(cpf_cnpj, nome) -> str:
    d = F.cnpj_digitos(cpf_cnpj)
    if len(d) == 14:
        return F.fmt_cnpj(d)
    if len(d) == 11:
        return d
    return "nome:" + F.norm(nome)


def _controlador(v) -> bool:
    return F.norm(v).startswith("s")


def carregar_fres(conn) -> dict[str, list[dict]]:
    """CNPJ (só dígitos) da companhia → linhas do FRE mais recente (maior data e, nela, maior versão)."""
    cols = ["cnpj_companhia", "data_referencia", "versao", "id_acionista", "id_acionista_relacionado", "acionista",
            "tipo_pessoa_acionista", "cpf_cnpj_acionista", "percentual_total_acoes_circulacao", "acionista_controlador"]
    sql = f"""
        WITH ult AS (
            SELECT cnpj_companhia, MAX(data_referencia || '|' || printf('%05d', versao)) AS k
            FROM fre_posicao_acionaria GROUP BY cnpj_companhia)
        SELECT {','.join('p.' + c for c in cols)} FROM fre_posicao_acionaria p
        JOIN ult u ON u.cnpj_companhia = p.cnpj_companhia
                  AND p.data_referencia || '|' || printf('%05d', p.versao) = u.k"""
    out: dict[str, list[dict]] = {}
    for r in conn.execute(sql):
        d = dict(zip(cols, r))
        out.setdefault(F.cnpj_digitos(d["cnpj_companhia"]), []).append(d)
    return out


def cadeia(cnpj: str, fres: dict[str, list[dict]]) -> list[dict]:
    """Controladores de `cnpj`, nível a nível, atravessando FREs de outras companhias da base."""
    out, vistos = {}, {F.cnpj_digitos(cnpj)}

    def subir_fre(cnpj_dig: str, nivel: int):
        linhas = fres.get(cnpj_dig)
        if not linhas or nivel > MAX_NIVEL:
            return
        por_rel: dict = {}
        for l in linhas:
            por_rel.setdefault(l["id_acionista_relacionado"], []).append(l)

        def descer(rel_id, nv):   # rel_id None = acionistas diretos da companhia
            if nv > MAX_NIVEL:
                return
            for l in por_rel.get(rel_id, []):
                if not _controlador(l["acionista_controlador"]):
                    continue
                doc = _doc(l["cpf_cnpj_acionista"], l["acionista"])
                if doc not in out or out[doc]["nivel"] > nv:
                    out[doc] = {"nivel": nv, "controlador_doc": doc, "controlador_nome": l["acionista"],
                                "tipo_pessoa": l["tipo_pessoa_acionista"],
                                "percentual": l["percentual_total_acoes_circulacao"],
                                "via_cnpj": l["cnpj_companhia"], "via_data_fre": l["data_referencia"]}
                if l["id_acionista"] is not None and l["id_acionista"] != rel_id:
                    descer(l["id_acionista"], nv + 1)
                dig = F.cnpj_digitos(l["cpf_cnpj_acionista"])
                if len(dig) == 14 and dig not in vistos and dig in fres:
                    vistos.add(dig)
                    subir_fre(dig, nv + 1)

        descer(None, nivel)

    subir_fre(F.cnpj_digitos(cnpj), 1)
    return sorted(out.values(), key=lambda x: (x["nivel"], x["controlador_doc"]))


def origens(conn) -> set[str]:
    sql = """
        SELECT emissor_cnpj FROM rf_ativos WHERE emissor_cnpj IS NOT NULL
        UNION SELECT devedor_cnpj FROM rf_ativos WHERE devedor_cnpj IS NOT NULL
        UNION SELECT cnpj FROM rf_partes WHERE cnpj IS NOT NULL AND papel <> 'agente_fiduciario'"""
    return {r[0] for r in conn.execute(sql)}


def reconstruir(conn) -> int:
    fres = carregar_fres(conn)
    linhas = []
    for cnpj in origens(conn):
        if F.cnpj_digitos(cnpj) not in fres:
            continue
        for c in cadeia(cnpj, fres):
            linhas.append((cnpj, c["nivel"], c["controlador_doc"], c["controlador_nome"], c["tipo_pessoa"],
                           c["percentual"], c["via_cnpj"], c["via_data_fre"]))
    conn.execute("DELETE FROM rf_grupo")
    conn.executemany("INSERT INTO rf_grupo (cnpj_origem, nivel, controlador_doc, controlador_nome, tipo_pessoa, "
                     "percentual, via_cnpj, via_data_fre) VALUES (?,?,?,?,?,?,?,?)", linhas)
    conn.commit()
    return len(linhas)


def main():
    conn = get_db()
    F.garantir_schema_rf(conn)
    n = reconstruir(conn)
    print(f"  rf_grupo: {n} elos de controle")


if __name__ == "__main__":
    main()
