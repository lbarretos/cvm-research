"""
Etapa 5: versão do template de contas da CVM, detectada filing a filing.

O código fixo (`st_conta_fixa = 'S'`) é estável dentro de uma versão do plano, mas a CVM já re-numerou
contas (IFRS 9 deslocou 1.02.01.03 em diante) e empresas voltam ao layout antigo no meio da série, então
a versão não se deduz da data. A "impressão digital" de um filing é o mapa código → nome normalizado das
suas contas S; dois filings são da mesma versão se nenhum código tem nome diferente entre eles (empresas
omitem contas S vazias, por isso é "não se contradizem", não "são iguais").

Saídas (tudo derivado de `demonstrativos_contabeis`, reconstruído a cada rodada):
  - `filings.versao_template`: 'v1', 'v2'… por (plano_contas, tipo_doc), numeradas pela data de aparição.
    NULL quando não dá para afirmar: filing compatível com mais de uma versão, ou plano com versões
    demais para a regra ser confiável (os bancos renomeiam contas S à vontade).
  - `plano_cvm`: as contas S de cada versão.
  - `plano_cvm_de_para`: para cada par de versões, os códigos que mudaram de lugar mas mantêm o nome.

    python scripts/ingest/template_versions.py        # recalcula a partir do DATABASE_URL
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

from utils import get_db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from consistency_utils import normalize_text  # noqa: E402

# Acima disto o agrupamento não é versão de template, é ruído de renomeação (DRE de banco chega a 19).
MAX_VERSOES_CONFIAVEIS = 4

DDL = """
CREATE TABLE IF NOT EXISTS plano_cvm (
    plano_contas   TEXT NOT NULL,
    tipo_doc       TEXT NOT NULL,
    versao_template TEXT NOT NULL,
    cd_conta       TEXT NOT NULL,
    ds_conta_norm  TEXT NOT NULL,
    PRIMARY KEY (plano_contas, tipo_doc, versao_template, cd_conta)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS plano_cvm_de_para (
    plano_contas TEXT NOT NULL,
    tipo_doc     TEXT NOT NULL,
    versao_a     TEXT NOT NULL,
    cd_a         TEXT NOT NULL,
    versao_b     TEXT NOT NULL,
    cd_b         TEXT NOT NULL,
    ds_conta_norm TEXT NOT NULL,
    PRIMARY KEY (plano_contas, tipo_doc, versao_a, versao_b, cd_a)
) WITHOUT ROWID;
"""


def garantir_esquema(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(filings)")}
    if "versao_template" not in cols:
        conn.execute("ALTER TABLE filings ADD COLUMN versao_template TEXT")
    conn.executescript(DDL)


def agrupar(itens: list[tuple[tuple, dict]]) -> tuple[list[dict], dict]:
    """itens = [(chave_do_filing, {cd: nome_norm})] já ordenados. Agrupamento guloso: cada filing entra na
    primeira versão compatível; conflito abre versão nova. Devolve (uniões por versão, {chave: [índices]})
    com TODOS os índices compatíveis no fim (para detectar ambiguidade)."""
    unioes: list[dict] = []
    for _, d in itens:
        for u in unioes:
            if all(u.get(cd, nm) == nm for cd, nm in d.items()):
                u.update(d)
                break
        else:
            unioes.append(dict(d))
    compat = {k: [i for i, u in enumerate(unioes) if all(u.get(cd, nm) == nm for cd, nm in d.items())]
              for k, d in itens}
    return unioes, compat


def detectar(conn) -> tuple[dict, dict]:
    """Devolve ({(plano, tipo_doc): [união código→nome por versão]}, {chave do filing: ('v1', ...) | None})."""
    plano = {(r[0], r[1], r[2]): r[3] for r in conn.execute(
        "SELECT cnpj_companhia, fonte, data_referencia, plano_contas FROM filings WHERE tipo_doc = 'DRE'")}
    fp: dict = defaultdict(dict)
    for cn, fo, td, dr, cd, ds in conn.execute("""
            SELECT f.cnpj_companhia, f.fonte, f.tipo_doc, f.data_referencia, d.cd_conta, d.ds_conta
            FROM filings f JOIN demonstrativos_contabeis d
              ON d.cnpj_companhia = f.cnpj_companhia AND d.fonte = f.fonte AND d.tipo_doc = f.tipo_doc
             AND d.data_referencia = f.data_referencia AND d.versao = f.versao
            WHERE d.ordem_exercicio = 'Último' AND d.st_conta_fixa = 'S'"""):
        fp[(cn, fo, td, dr)].setdefault(cd, normalize_text(ds))

    grupos: dict = defaultdict(list)
    for k, d in fp.items():
        grupos[(plano.get((k[0], k[1], k[3])) or "padrao", k[2])].append((k, d))

    versoes, atribuicao = {}, {}
    for g, itens in grupos.items():
        itens.sort(key=lambda x: (x[0][3], x[0][0], x[0][1]))
        unioes, compat = agrupar(itens)
        confiavel = len(unioes) <= MAX_VERSOES_CONFIAVEIS or g[0] == "padrao"
        votos = [defaultdict(Counter) for _ in unioes]
        for k, d in itens:
            c = compat[k]
            atribuicao[k] = f"v{c[0] + 1}" if confiavel and len(c) == 1 else None
            if atribuicao[k]:
                for cd, nm in d.items():
                    votos[c[0]][cd][nm] += 1
        # A união absorve contas de filings compatíveis com várias versões (que omitem as contas que as
        # distinguem), então o plano de cada versão sai do voto só dos filings atribuídos sem ambiguidade.
        versoes[g] = [{cd: cont.most_common(1)[0][0] for cd, cont in v.items()} for v in votos]
    return versoes, atribuicao


def _pai(cd: str) -> str:
    return cd.rsplit(".", 1)[0] if "." in cd else ""


def derivar_de_para(versoes: dict) -> list[tuple]:
    """Códigos que mudaram de posição mas mantêm o nome entre duas versões do mesmo (plano, tipo_doc).
    A chave é (pai, nome): o nome sozinho se repete ("Contas a Receber" no circulante e no não
    circulante), e o deslocamento do IFRS 9 acontece dentro do mesmo pai (1.02.01.0x)."""
    out = []
    for (pl, td), unioes in versoes.items():
        for a in range(len(unioes)):
            for b in range(a + 1, len(unioes)):
                por_chave_a, por_chave_b = defaultdict(list), defaultdict(list)
                for cd, nm in unioes[a].items():
                    por_chave_a[(_pai(cd), nm)].append(cd)
                for cd, nm in unioes[b].items():
                    por_chave_b[(_pai(cd), nm)].append(cd)
                for (pai, nm), cds_a in por_chave_a.items():
                    cds_b = por_chave_b.get((pai, nm))
                    # Só nome único dos dois lados. O mesmo nome em dois códigos ("Outros ativos não
                    # circulantes" em .09 e .10 na v1) é ambíguo: tentar resolver por exclusão colidiu com
                    # filings que têm os dois códigos e piorou a Camada 3 (338 → 1.312 no BPA de 2017).
                    if cds_b and len(cds_a) == 1 and len(cds_b) == 1 and cds_a[0] != cds_b[0]:
                        out.append((pl, td, f"v{a + 1}", cds_a[0], f"v{b + 1}", cds_b[0], nm))
    return out


def atribuir_versoes(conn) -> dict:
    """Recalcula e grava versao_template, plano_cvm e plano_cvm_de_para. Devolve contagens."""
    garantir_esquema(conn)
    versoes, atribuicao = detectar(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE filings SET versao_template = NULL")
        conn.executemany(
            "UPDATE filings SET versao_template = ? WHERE cnpj_companhia = ? AND fonte = ? AND tipo_doc = ? "
            "AND data_referencia = ?", [(v, *k) for k, v in atribuicao.items() if v])
        conn.execute("DELETE FROM plano_cvm")
        conn.executemany("INSERT INTO plano_cvm VALUES (?,?,?,?,?)", [
            (pl, td, f"v{i + 1}", cd, nm)
            for (pl, td), us in versoes.items() for i, u in enumerate(us) for cd, nm in u.items()])
        conn.execute("DELETE FROM plano_cvm_de_para")
        conn.executemany("INSERT INTO plano_cvm_de_para VALUES (?,?,?,?,?,?,?)", derivar_de_para(versoes))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"filings_com_versao": sum(1 for v in atribuicao.values() if v),
            "filings_sem_versao": sum(1 for v in atribuicao.values() if not v)}


def main() -> None:
    conn = get_db()
    print(atribuir_versoes(conn))


if __name__ == "__main__":
    main()
