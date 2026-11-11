"""
Resolução de devedores de CRI e CRA (rf_ativos.devedor_cnpj).

Cruza o devedor_nome publicado pela ANBIMA (onde o CNPJ costuma vir nulo)
contra a tabela companies (watchlist B3+CVM), empresas cadastradas na CVM e
dicionário de apelidos canônicos de emissores corporativos.

Preenche rf_ativos.devedor_cnpj e atualiza rf_partes (papel='devedor'),
permitindo conectar o CRI/CRA à estrutura contábil, ao grupo econômico
e aos documentos do devedor real.

Uso:
  python scripts/ingest/rf_devedor_resolucao.py           # executa e grava
  python scripts/ingest/rf_devedor_resolucao.py --dry-run # apenas exibe estatísticas
"""
import argparse
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR / "scripts" / "ingest") not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR / "scripts" / "ingest"))

from utils import get_db


def sem_acento(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def norm_tokens(s: str) -> set[str]:
    s = sem_acento(s).upper()
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = s.split()
    stop = {
        "SA", "S", "A", "LTDA", "EIRELI", "CIA", "COMPANHIA", "PARTICIPACOES", "PARTICIPACAO",
        "PART", "EMPREENDIMENTOS", "EMPREEND", "EMP", "DE", "DA", "DO", "DOS", "DAS", "E",
        "ALIMENTOS", "ENGENHARIA", "COMERCIO", "INDUSTRIA", "SERVICOS", "HOLDING", "SOCIETARIA",
        "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"
    }
    return {t for t in tokens if t not in stop and len(t) > 1}


APELIDOS_CANONICOS = {
    # Watchlist / Listadas
    "BRF": ("01.838.723/0001-27", "BRFS3", "BRF S.A."),
    "HYPERA": ("02.932.074/0001-91", "HYPE3", "HYPERA S.A."),
    "JBS": ("02.916.265/0001-60", "JBSS3", "JBS S.A."),
    "MULTIPLAN": ("07.816.890/0001-53", "MULT3", "MULTIPLAN EMPREENDIMENTOS IMOBILIÁRIOS S.A."),
    "LOCALIZA": ("16.670.085/0001-55", "RENT3", "LOCALIZA RENT A CAR S.A."),
    "BTG PACTUAL": ("30.306.294/0001-45", "BPAC11", "BANCO BTG PACTUAL S.A."),
    "SEARA": ("02.914.460/0001-50", "JBSS3", "SEARA ALIMENTOS LTDA."),
    "MATEUS": ("03.995.515/0001-03", "GMAT3", "GRUPO MATEUS S.A."),
    "ZAMP": ("13.574.594/0001-96", "ZAMP3", "ZAMP S.A."),
    "ELDORADO BRASIL": ("07.401.436/0001-30", "AALM3", "ELDORADO BRASIL CELULOSE S.A."),
    "IPIRANGA": ("33.337.122/0001-27", "UGPA3", "IPIRANGA PRODUTOS DE PETRÓLEO S.A."),
    "DASA": ("61.486.650/0001-83", "DASA3", "DIAGNOSTICOS DA AMERICA SA"),
    "DIAGNOSTICOS DA AMERICA": ("61.486.650/0001-83", "DASA3", "DIAGNOSTICOS DA AMERICA SA"),
    "ULTRA SOM": ("61.486.650/0001-83", "DASA3", "DIAGNOSTICOS DA AMERICA SA"),
    "UNIDAS": ("04.973.092/0001-22", "RENT3", "COMPANHIA DE LOCAÇÃO DAS AMÉRICAS"),
    "COMPANHIA DE LOCACAO DAS AMERICAS": ("04.973.092/0001-22", "RENT3", "COMPANHIA DE LOCAÇÃO DAS AMÉRICAS"),
    "BCBF": ("05.197.443/0001-38", "HAPV3", "HAPVIDA PARTICIPACOES E INVESTIMENTOS S.A."),
    "ALLOS": ("05.444.155/0001-63", "ALOS3", "ALLOS S.A."),
    "ALIANSCE SONAE": ("05.444.155/0001-63", "ALOS3", "ALLOS S.A."),
    "ASSAI": ("06.057.223/0001-71", "ASAI3", "SENDAS DISTRIBUIDORA S.A."),
    "SOMA": ("10.744.828/0001-00", "ALPA4", "GRUPO DE MODA SOMA S.A."),
    "CIDADE MARAVILHOSA": ("10.744.828/0001-00", "ALPA4", "GRUPO DE MODA SOMA S.A."),
    "CURY": ("08.797.760/0001-83", "CURY3", "CURY CONSTRUTORA E INCORPORADORA S.A."),
    "JHSF": ("08.294.224/0001-65", "JHSF3", "JHSF PARTICIPAÇÕES S.A."),
    "DIRECIONAL": ("16.614.075/0001-00", "DIRR3", "DIRECIONAL ENGENHARIA S.A."),
    "EVEN": ("43.470.988/0001-65", "EVEN3", "EVEN CONSTRUTORA E INCORPORADORA S.A."),
    "COGNA": ("02.800.026/0001-40", "COGN3", "COGNA EDUCAÇÃO S.A."),
    "M. DIAS BRANCO": ("07.206.816/0001-83", "MDIA3", "M. DIAS BRANCO S.A."),
    "CSN CIMENTOS": ("12.049.631/0001-84", "CSNA3", "CSN CIMENTOS S.A."),
    "BR PROPERTIES": ("06.977.745/0001-91", "BRPR3", "BR PROPERTIES S.A."),
    "DEXCO": ("97.837.181/0001-47", "DXCO3", "DEXCO S.A."),
    "PETROBRAS DISTRIBUIDORA": ("34.274.233/0001-02", "VBBR3", "VIBRA ENERGIA S.A."),
    "MINERVA": ("67.620.377/0001-14", "BEEF3", "MINERVA S.A."),
    "ANIMA": ("09.288.252/0001-32", "ANIM3", "ANIMA HOLDING S/A"),
    "IGUATEMI": ("60.543.816/0001-93", "IGTI11", "IGUATEMI S.A."),
    "SLC": ("89.096.457/0001-55", "SLCE3", "SLC AGRICOLA SA"),
    "BOA SAFRA": ("16.299.719/0001-05", "SOJA3", "BOA SAFRA SEMENTES S.A."),
    "SAO CARLOS": ("02.992.658/0001-50", "SCAR3", "SÃO CARLOS EMPREENDIMENTOS E PARTICIPAÇÕES S.A."),
    "CARAMURU": ("00.080.671/0001-00", "CRMU", "CARAMURU ALIMENTOS S.A."),
    # Emissoras de Dívida / Cooperativas / S.A.s não listadas
    "FS INDUSTRIA": ("46.710.597/0001-69", "FSII", "FS I INDUSTRIA DE ETANOL S.A"),
    "FS BIOCOMBUSTIVEIS": ("46.710.597/0001-69", "FSII", "FS I INDUSTRIA DE ETANOL S.A"),
    "FS AGRISOLUTIONS": ("46.710.597/0001-69", "FSII", "FS I INDUSTRIA DE ETANOL S.A"),
    "FS FLORESTAL": ("46.710.597/0001-69", "FSII", "FS I INDUSTRIA DE ETANOL S.A"),
    "LAR COOPERATIVA": ("76.778.077/0001-30", None, "LAR COOPERATIVA AGROINDUSTRIAL"),
    "COCAL": ("51.026.045/0001-92", None, "COCAL COMÉRCIO INDÚSTRIA CANAÃ AÇÚCAR E ÁLCOOL LTDA."),
    "C. VALE": ("77.858.639/0001-44", None, "C. VALE - COOPERATIVA AGROINDUSTRIAL"),
    "BEM BRASIL": ("07.962.152/0001-52", None, "BEM BRASIL ALIMENTOS S.A."),
    "VICUNHA": ("07.273.498/0001-90", None, "VICUNHA TEXTIL S.A."),
    "SAO SALVADOR": ("02.540.354/0001-62", None, "SÃO SALVADOR ALIMENTOS S.A."),
    "SOROCABA REFRESCOS": ("44.757.268/0001-83", None, "SOROCABA REFRESCOS S.A."),
    "REFRESCOS BANDEIRANTES": ("01.077.584/0001-09", None, "REFRESCOS BANDEIRANTES INDÚSTRIA E COMÉRCIO LTDA."),
    "NORSA": ("07.196.033/0001-10", None, "NORSA REFRIGERANTES S.A."),
    "OLFAR": ("90.793.852/0001-20", None, "OLFAR S.A. ALIMENTO E ENERGIA"),
    "NEOMILLE": ("25.323.003/0001-06", None, "NEOMILLE S.A."),
    "NATURAL ONE": ("18.665.340/0001-85", None, "NATURAL ONE S.A"),
    "ACO VERDE": ("09.117.202/0001-54", None, "AÇO VERDE DO BRASIL S.A."),
    "PATRIMAR": ("17.472.274/0001-00", None, "PATRIMAR ENGENHARIA S.A."),
    "PACAEMBU": ("10.257.908/0001-39", None, "PACAEMBU CONSTRUTORA S.A."),
    "NARDINI": ("51.815.173/0001-01", None, "NARDINI AGROINDUSTRIAL LTDA."),
    "MADERO": ("12.597.287/0001-00", None, "MADERO INDÚSTRIA E COMÉRCIO S.A."),
    "J. MACEDO": ("06.598.633/0001-60", None, "J. MACÊDO S.A."),
    "INTEGRADA COOPERATIVA": ("00.999.018/0001-34", None, "INTEGRADA COOPERATIVA AGROINDUSTRIAL"),
    "GDM GENETICA": ("14.509.845/0001-89", None, "GDM GENÉTICA DO BRASIL S.A."),
    "FLORA PRODUTOS": ("07.401.436/0001-30", None, "FLORA PRODUTOS DE HIGIENE E LIMPEZA S.A."),
    "COOXUPE": ("20.672.639/0001-08", None, "COOPERATIVA REGIONAL DE CAFEICULTORES EM GUAXUPE LTDA"),
    "COLOMBO AGROINDUSTRIA": ("48.334.338/0001-20", None, "COLOMBO AGROINDÚSTRIA S.A."),
    "CEREAL COMERCIO": ("01.696.536/0001-40", None, "CEREAL COMÉRCIO EXPORTAÇÃO E REPRESENTAÇÃO AGROPECUÁRIA S.A."),
    "CENTRAL CRESOL": ("03.447.886/0001-02", None, "CENTRAL CRESOL BASER"),
    "ALIBEM": ("03.238.564/0001-28", None, "ALIBEM ALIMENTOS S.A."),
    "ADUBOS ARAGUAIA": ("01.378.899/0001-59", None, "ADUBOS ARAGUAIA INDÚSTRIA E COMÉRCIO LTDA."),
    "EINSTEIN": ("60.765.823/0001-30", None, "SOCIEDADE BENEFICENTE ISRAELITA BRASILEIRA HOSPITAL ALBERT EINSTEIN"),
    "HOSPITAL ALBERT EINSTEIN": ("60.765.823/0001-30", None, "SOCIEDADE BENEFICENTE ISRAELITA BRASILEIRA HOSPITAL ALBERT EINSTEIN"),
    "USINA SANTA FE": ("47.511.456/0001-08", None, "USINA SANTA FE S.A."),
    "USINA CERRADAO": ("08.318.966/0001-02", None, "USINA CERRADAO S.A."),
    "VALE DO TIJUCO": ("08.384.453/0001-06", None, "VALE DO TIJUCO AÇÚCAR E ÁLCOOL S.A."),
    "QUATA": ("46.228.426/0001-04", None, "ACUCAREIRA QUATA S.A."),
    "PISANI": ("88.614.995/0001-98", None, "PISANI PLASTICOS S.A."),
    "GJA": ("11.196.790/0001-54", None, "GJA INDUSTRIAS S.A."),
    "CHARRUA": ("01.597.106/0001-70", None, "DISTRIBUIDORA DE PRODUTOS DE PETROLEO CHARRUA LTDA."),
    "BTSA": ("14.150.155/0001-44", None, "BTSA - BAHIA TERMINAIS S.A."),
}


def carregar_companies(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT cnpj, ticker, nome_cvm FROM companies")
    companies = []
    for r in cur.fetchall():
        companies.append({
            "cnpj": r[0],
            "ticker": r[1],
            "nome": r[2],
            "norm": sem_acento(r[2]).upper(),
            "tokens": norm_tokens(r[2]),
        })
    return companies


def resolver_devedor(dnome: str, companies: list[dict] | None = None) -> dict | None:
    """Resolve o nome do devedor contra apelidos conhecidos ou tabela companies."""
    if not dnome:
        return None
    d_norm = sem_acento(dnome).upper()
    d_toks = norm_tokens(dnome)

    # 1. Dicionário de apelidos canônicos
    for apelido, info in APELIDOS_CANONICOS.items():
        if sem_acento(apelido).upper() in d_norm:
            return {"cnpj": info[0], "ticker": info[1], "nome": info[2], "metodo": "apelido_canonico"}

    # 2. Tabela companies
    if companies:
        for c in companies:
            if c["norm"] in d_norm or d_norm in c["norm"]:
                return {"cnpj": c["cnpj"], "ticker": c["ticker"], "nome": c["nome"], "metodo": "nome_substring"}
            inter = d_toks & c["tokens"]
            if len(inter) >= 2 and (len(inter) == len(d_toks) or len(inter) == len(c["tokens"])):
                return {"cnpj": c["cnpj"], "ticker": c["ticker"], "nome": c["nome"], "metodo": "tokens"}

    return None


def executar_resolucao(conn: sqlite3.Connection, dry_run: bool = False, verbose: bool = False) -> tuple[int, int]:
    """Varre todos os títulos de CRI e CRA em rf_ativos com devedor_cnpj nulo e preenche o CNPJ."""
    companies = carregar_companies(conn)

    cur = conn.execute("""
        SELECT codigo, tipo, devedor_nome 
        FROM rf_ativos 
        WHERE tipo IN ('CRI', 'CRA') AND devedor_nome IS NOT NULL AND devedor_cnpj IS NULL
        ORDER BY codigo
    """)
    ativos = cur.fetchall()

    if not ativos:
        if verbose:
            print("Nenhum CRI/CRA com devedor_cnpj nulo.")
        return 0, 0

    resolvidos = 0
    updates_ativos = []
    updates_partes = []

    for cod, tipo, dnome in ativos:
        match = resolver_devedor(dnome, companies)
        if match and match.get("cnpj"):
            resolvidos += 1
            updates_ativos.append((match["cnpj"], cod))
            updates_partes.append((match["cnpj"], cod))
            if verbose:
                t_str = f" ({match['ticker']})" if match.get("ticker") else ""
                print(f"  {cod:<12} [{tipo}] '{dnome}' -> {match['cnpj']}{t_str} via {match['metodo']}")

    if not dry_run and updates_ativos:
        conn.executemany("UPDATE rf_ativos SET devedor_cnpj = ? WHERE codigo = ?", updates_ativos)
        # Sincroniza também a tabela rf_partes para o papel de devedor
        conn.executemany(
            "UPDATE rf_partes SET cnpj = ? WHERE codigo = ? AND papel = 'devedor' AND cnpj IS NULL",
            updates_partes,
        )
        # Garante que se o devedor não estava em rf_partes com CNPJ, passa a constar
        for cnpj, cod in updates_ativos:
            conn.execute("""
                INSERT OR IGNORE INTO rf_partes (chave, codigo, papel, cnpj, nome, fonte, confianca)
                SELECT codigo || '|devedor|' || devedor_cnpj || '|resolucao_devedor',
                       codigo, 'devedor', devedor_cnpj, devedor_nome, 'resolucao_devedor', 1.0
                FROM rf_ativos WHERE codigo = ? AND devedor_cnpj IS NOT NULL
            """, (cod,))
        conn.commit()

    return resolvidos, len(ativos)


def main():
    parser = argparse.ArgumentParser(description="Resolve devedor_cnpj para CRIs e CRAs")
    parser.add_argument("--dry-run", action="store_true", help="Preview sem persistir alterações")
    parser.add_argument("--verbose", "-v", action="store_true", help="Exibe cada ativo resolvido")
    args = parser.parse_args()

    conn = get_db()
    try:
        resolvidos, total = executar_resolucao(conn, dry_run=args.dry_run, verbose=args.verbose or args.dry_run)
        pct = (resolvidos / total * 100) if total else 0.0
        modo = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{modo}Resolução de devedores concluída: {resolvidos} / {total} ativos resolvidos ({pct:.1f}%).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
