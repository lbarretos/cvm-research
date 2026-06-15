"""
Adiciona empresas do catálogo B3+CVM ao watchlist.csv e à tabela companies.

Usage:
  python add_companies.py --ibov                    # Somente IBOV (~78 empresas)
  python add_companies.py --ibrx                    # Somente IBRX-100
  python add_companies.py --all                     # Todas B3 ativas (~443)
  python add_companies.py --ticker PETR4            # Uma empresa específica
  python add_companies.py --setor "Saude"           # Por setor (deve constar no catálogo)
  python add_companies.py --ibov --dry-run          # Preview sem gravar
  python add_companies.py --ibov --skip-assumed     # Pula tickers com sufixo assumido

Após adicionar ao watchlist.csv, rode ingest_companies.py para sincronizar
a tabela companies e depois os demais ingestores para popular os dados.
"""

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

WATCHLIST_PATH = Path(__file__).parents[2] / "watchlist.csv"
CATALOG_PATH   = Path(__file__).parents[2] / "company_catalog.csv"

# Mapeamento de setor_cvm (CVM) para o vocabulário da watchlist.
# Os valores são os campos SETOR_ATIV do cadastro CVM.
SETOR_MAP: dict[str, str] = {
    # Saúde
    "Serviços Médicos":                                         "Saude",
    "Farmacêutico e Higiene":                                   "Saude",
    "Farmacêuticos e Outros":                                   "Saude",
    "Medicamentos":                                             "Saude",
    "Planos de Saúde":                                          "Saude",
    "Serv.Méd.Hospit..Análises e Diagnósticos":                 "Saude",
    # Industrial
    "Metalurgia e Siderurgia":                                  "Industrial",
    "Emp. Adm. Part. - Metalurgia e Siderurgia":                "Industrial",
    "Máquinas, Equipamentos, Veículos e Peças":                 "Industrial",
    "Emp. Adm. Part. - Máqs., Equip., Veíc. e Peças":          "Industrial",
    "Máq. e Equip. Industriais":                                "Industrial",
    "Material de Construção":                                   "Industrial",
    "Papel e Celulose":                                         "Industrial",
    "Química":                                                  "Industrial",
    "Embalagens":                                               "Industrial",
    "Petroquímicos e Borracha":                                 "Industrial",
    "Têxtil e Vestuário":                                       "Industrial",
    "Vestuário e Calçados":                                     "Industrial",
    "Motores . Compressores e Outros":                          "Industrial",
    # Mobilidade
    "Serviços Transporte e Logística":                          "Mobilidade",
    "Emp. Adm. Part. - Serviços Transporte e Logística":        "Mobilidade",
    "Aluguel de carros":                                        "Mobilidade",
    "Transporte Rodoviário":                                    "Mobilidade",
    "Transporte Ferroviário":                                   "Mobilidade",
    "Logística":                                                "Mobilidade",
    "Serviços de Logística":                                    "Mobilidade",
    # Agro
    "Agricultura (Açúcar, Álcool e Cana)":                      "Agro",
    "Agricultura":                                              "Agro",
    "Produtos Agropecuários":                                   "Agro",
    "Sementes e Adubos":                                        "Agro",
    "Alimentos Processados":                                    "Agro",
    "Alimentos":                                                "Agro",
    "Emp. Adm. Part. - Alimentos":                              "Agro",
    "Açúcar e Álcool":                                          "Agro",
    # Educação
    "Educação":                                                 "Educacao",
    "Emp. Adm. Part. - Educação":                               "Educacao",
    # Infraestrutura
    "Saneamento, Serv. Água e Gás":                             "Infraestrutura",
    "Emp. Adm. Part. - Saneamento, Serv. Água e Gás":           "Infraestrutura",
    "Exploração de Rodovias":                                   "Infraestrutura",
    "Água e Saneamento":                                        "Infraestrutura",
    "Transportes":                                              "Infraestrutura",
    "Serviços Portuários":                                      "Infraestrutura",
    "Aeroportos":                                               "Infraestrutura",
    # Aviação
    "Transporte Aéreo":                                         "Aviacao",
    # Imobiliário
    "Construção Civil, Mat. Constr. e Decoração":               "Imobiliario",
    "Emp. Adm. Part. - Const. Civil, Mat. Const. e Decoração":  "Imobiliario",
    "Exploração de Imóveis":                                    "Imobiliario",
    "Incorporações":                                            "Imobiliario",
    "Construção Civil":                                         "Imobiliario",
    # Energia
    "Energia Elétrica":                                         "Energia",
    "Emp. Adm. Part. - Energia Elétrica":                       "Energia",
    "Petróleo e Gás":                                           "Energia",
    "Emp. Adm. Part. - Petróleo e Gás":                         "Energia",
    "Petróleo. Gás e Biocombustíveis":                          "Energia",
    "Exploração. Refino e Distribuição":                        "Energia",
    # Telecom
    "Telecomunicações":                                         "Telecom",
    "Emp. Adm. Part. - Telecomunicações":                       "Telecom",
    # Financeiro
    "Bancos":                                                   "Financeiro",
    "Emp. Adm. Part. - Bancos":                                 "Financeiro",
    "Seguradoras e Corretoras":                                 "Financeiro",
    "Emp. Adm. Part. - Seguradoras e Corretoras":               "Financeiro",
    "Intermediação Financeira":                                 "Financeiro",
    "Emp. Adm. Part. - Intermediação Financeira":               "Financeiro",
    "Arrendamento Mercantil":                                   "Financeiro",
    "Securitização de Recebíveis":                              "Financeiro",
    "Bolsas de Valores/Mercadorias e Futuros":                  "Financeiro",
    "Gestão de Recursos e Investimentos":                       "Financeiro",
    "Emp. Adm. Part. - Financeiras":                            "Financeiro",
    "Serviços Financeiros Especializados":                      "Financeiro",
    # Turismo
    "Hospedagem e Turismo":                                     "Turismo",
    "Hotéis e Restaurantes":                                    "Turismo",
    "Turismo e Lazer":                                          "Turismo",
    "Operadoras e Agências":                                    "Turismo",
    "Brinquedos e Lazer":                                       "Turismo",
    # Varejo
    "Comércio (Atacado e Varejo)":                              "Varejo",
    "Emp. Adm. Part. - Comércio (Atacado e Varejo)":            "Varejo",
    "Eletrodomésticos":                                         "Varejo",
    "Têxtil e Vestuário":                                       "Varejo",
    # Tecnologia
    "Comunicação e Informática":                                "Tecnologia",
    "Emp. Adm. Part. - Comunicação e Informática":              "Tecnologia",
    "Programas e Serviços":                                     "Tecnologia",
    "Tecnologia":                                               "Tecnologia",
    # Mineração
    "Extração Mineral":                                         "Mineracao",
    "Emp. Adm. Part. - Extração Mineral":                       "Mineracao",
    "Minerais Metálicos":                                       "Mineracao",
    "Mineração":                                                "Mineracao",
}


def load_watchlist() -> dict[str, dict]:
    """Retorna dict cnpj → row do watchlist.csv."""
    rows = {}
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["cnpj"]] = row
    return rows


def load_catalog() -> pd.DataFrame:
    """Carrega o catálogo. Gera se não existir."""
    if not CATALOG_PATH.exists():
        print("Catálogo não encontrado. Gerando agora...")
        # Importa e chama build_catalog() inline
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "catalog.py")],
            capture_output=False
        )
        if result.returncode != 0:
            print("Erro ao gerar catálogo. Rode 'python catalog.py' manualmente.", file=sys.stderr)
            sys.exit(1)
    return pd.read_csv(CATALOG_PATH, dtype=str).fillna("")


def map_setor(setor_cvm: str) -> str:
    """Converte setor CVM para o vocabulário da watchlist."""
    return SETOR_MAP.get(setor_cvm.strip(), "Outros")


def candidates_from_catalog(
    catalog: pd.DataFrame,
    watchlist: dict,
    *,
    ibov: bool = False,
    ibrx: bool = False,
    all_b3: bool = False,
    ticker: str | None = None,
    setor: str | None = None,
    skip_assumed: bool = False,
) -> pd.DataFrame:
    """Retorna empresas do catálogo que NÃO estão no watchlist."""
    df = catalog.copy()

    # Filtros de escopo
    if ticker:
        df = df[df["ticker"].str.upper() == ticker.upper()]
    elif ibov and not ibrx:
        df = df[df["indices"].str.contains("IBOV", na=False)]
    elif ibrx and not ibov:
        df = df[df["indices"].str.contains("IBRX", na=False)]
    elif ibov and ibrx:
        df = df[df["indices"].str.len().gt(0)]
    # all_b3: não filtra

    if setor:
        setor_lower = setor.lower()
        mask = (
            df["setor_cvm"].str.lower().str.contains(setor_lower, na=False) |
            df["indices"].str.lower().str.contains(setor_lower, na=False)
        )
        df = df[mask]

    if skip_assumed:
        df = df[df["ticker_confidence"] != "assumed"]

    # Remove os que já estão no watchlist
    existing_cnpjs = set(watchlist.keys())
    df = df[~df["cnpj"].isin(existing_cnpjs)]

    return df.reset_index(drop=True)


def to_watchlist_rows(candidates: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in candidates.iterrows():
        rows.append({
            "ticker":     r["ticker"],
            "cnpj":       r["cnpj"],
            "codigo_cvm": r["codigo_cvm"],
            "nome_cvm":   r["nome_cvm"] or r["nome_b3"],
            "setor":      map_setor(r.get("setor_cvm", "")),
            "status_cvm": "ATIVO",
            "observacao": f"auto:{r.get('ticker_confidence','')}" if r.get("ticker_confidence") == "assumed" else "",
        })
    return rows


def append_to_watchlist(rows: list[dict]) -> None:
    """Adiciona novas linhas ao watchlist.csv preservando o existente."""
    fieldnames = ["ticker", "cnpj", "codigo_cvm", "nome_cvm", "setor", "status_cvm", "observacao"]
    with open(WATCHLIST_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in rows:
            writer.writerow(row)


def print_preview(rows: list[dict]) -> None:
    print(f"\n{'TICKER':<8} {'CNPJ':<22} {'NOME':<45} {'SETOR':<15} {'CONF'}")
    print("-" * 110)
    for r in rows:
        conf = "(assumed)" if "assumed" in r.get("observacao", "") else ""
        print(f"{r['ticker']:<8} {r['cnpj']:<22} {r['nome_cvm'][:44]:<45} {r['setor']:<15} {conf}")


def main():
    parser = argparse.ArgumentParser(description="Adiciona empresas ao watchlist.csv")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ibov",   action="store_true", help="Empresas do IBOV atual")
    group.add_argument("--ibrx",   action="store_true", help="Empresas do IBRX-100")
    group.add_argument("--all",    action="store_true", help="Todas as empresas B3 ativas")
    group.add_argument("--ticker", metavar="TICKER",    help="Uma empresa por ticker")
    parser.add_argument("--setor",        metavar="SETOR", help="Filtrar por setor (parcial)")
    parser.add_argument("--dry-run",      action="store_true", help="Preview sem gravar")
    parser.add_argument("--skip-assumed", action="store_true", help="Pula tickers com sufixo assumido")
    args = parser.parse_args()

    catalog   = load_catalog()
    watchlist = load_watchlist()

    candidates = candidates_from_catalog(
        catalog, watchlist,
        ibov=args.ibov,
        ibrx=args.ibrx,
        all_b3=args.all,
        ticker=args.ticker,
        setor=args.setor,
        skip_assumed=args.skip_assumed,
    )

    if candidates.empty:
        print("Nenhuma empresa nova encontrada (todas já estão no watchlist).")
        return

    rows = to_watchlist_rows(candidates)

    assumed = sum(1 for r in rows if "assumed" in r.get("observacao", ""))
    print(f"\n{len(rows)} empresa(s) para adicionar ({assumed} com ticker assumido)")
    print_preview(rows)

    if args.dry_run:
        print("\n[DRY RUN] Nenhuma alteração gravada.")
        return

    if assumed and not args.all:
        print(f"\n⚠  {assumed} ticker(s) têm sufixo assumido (ex: XXXX3).")
        print("   Verifique e corrija antes de rodar os ingestores.")
        print("   Use --skip-assumed para excluí-los, ou --dry-run para revisar primeiro.")

    confirm = input(f"\nAdicionar {len(rows)} empresa(s) ao watchlist.csv? [s/N] ").strip().lower()
    if confirm != "s":
        print("Cancelado.")
        return

    append_to_watchlist(rows)
    print(f"\n✓ {len(rows)} empresa(s) adicionadas ao watchlist.csv")
    print("\nPróximos passos:")
    print("  1. Revisar watchlist.csv — corrigir tickers com '(assumed)' em observacao")
    print("  2. python ingest_companies.py    # sincroniza tabela companies")
    print("  3. python ingest_ipe.py --desde 2009   # opcional: histórico completo")
    print("  4. python ingest_dfp.py --historico --desde 2010")
    print("  5. python ingest_itr.py --desde 2011")
    print("  6. python ingest_vlmo.py --desde 2018")
    print("  7. python ingest_fre.py --desde 2010")


if __name__ == "__main__":
    main()
