"""
Baixa e combina o catálogo de empresas listadas na B3 com o cadastro da CVM.

Gera company_catalog.csv na raiz do projeto com:
  ticker, cnpj, codigo_cvm, nome_cvm, nome_b3, setor_cvm, indices, segment_b3

Sources:
  - B3 API: issuingCompany, CNPJ, codeCVM, segment (market level)
  - B3 índices API: tickers completos (ON/PN/UNT) para IBOV e IBRX-100
  - CVM cad_cia_aberta.csv: nome oficial, setor_ativ, categ_reg

Usage:
  python catalog.py            # Gera/atualiza company_catalog.csv
  python catalog.py --search   # Pesquisa interativa por nome ou ticker
"""

import argparse
import base64
import io
import json
import sys
from pathlib import Path

import httpx
import pandas as pd

from utils import _http_get

CATALOG_PATH = Path(__file__).parents[2] / "company_catalog.csv"
CVM_CAD_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
B3_COMPANIES_BASE = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/{payload}"
B3_INDEX_BASE = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{payload}"

# Segmentos B3 que indicam ação listada em bolsa (marketIndicator values)
LISTED_SEGMENTS = {"7", "8", "14", "16", "17", "18"}

# Mapeamento de índice → payload base64
INDICES = {
    "IBOV":   {"language": "pt-br", "pageNumber": 1, "pageSize": 100, "index": "IBOV",   "segment": "1"},
    "IBRX":   {"language": "pt-br", "pageNumber": 1, "pageSize": 200, "index": "IBRX",   "segment": "1"},
}


def _b64(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def fetch_b3_companies() -> pd.DataFrame:
    """Baixa todas as empresas da B3 (equity, non-BDR, listadas)."""
    print("Baixando empresas da B3...")
    payload = _b64({"language": "pt-br", "issuingCompany": ""})
    url = B3_COMPANIES_BASE.format(payload=payload)
    r = _http_get(url, timeout=60)
    df = pd.DataFrame(r.json()["results"])

    # Filtrar: ativas, equity (type=1), nos segmentos listados, sem BDR
    df = df[
        (df["status"] == "A") &
        (df["type"] == "1") &
        (df["marketIndicator"].isin(LISTED_SEGMENTS)) &
        (~df["typeBDR"].str.len().gt(0))
    ].copy()

    df["cnpj_fmt"] = df["cnpj"].apply(_format_cnpj)
    df = df.dropna(subset=["cnpj_fmt"]).copy()
    print(f"  {len(df)} empresas equity ativas na B3")
    return df


def fetch_index_tickers(index_name: str) -> dict[str, str]:
    """Retorna {ticker_completo: issuingCompany} para um índice B3."""
    payload = _b64(INDICES[index_name])
    url = B3_INDEX_BASE.format(payload=payload)
    try:
        r = _http_get(url, timeout=30)
        items = r.json().get("results", [])
        return {item["cod"]: item["asset"] for item in items}
    except Exception as e:
        print(f"  AVISO: não foi possível baixar {index_name}: {e}", file=sys.stderr)
        return {}


def fetch_cvm_catalog() -> pd.DataFrame:
    """Baixa o cadastro de cias abertas da CVM."""
    print("Baixando cadastro CVM...")
    r = _http_get(CVM_CAD_URL, timeout=60)
    df = pd.read_csv(io.BytesIO(r.content), sep=";", encoding="latin-1", dtype=str)
    df = df[df["SIT"] == "ATIVO"].copy()
    print(f"  {len(df)} empresas ativas no cadastro CVM")
    return df


def _format_cnpj(raw: str) -> str | None:
    c = str(raw).strip().zfill(14)
    if len(c) != 14 or c in ("00000000000000", "0"):
        return None
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"


def build_ticker_map(b3_df: pd.DataFrame) -> dict[str, str]:
    """
    Constrói mapeamento issuingCompany → ticker_completo.

    Prioridade:
    1. Ticker do IBOV (mais conhecido e preciso)
    2. Ticker do IBRX-100
    3. issuingCompany + "3" (assumido ON — pode estar errado)
    """
    print("Baixando composição de índices B3...")
    ibov = fetch_index_tickers("IBOV")
    ibrx = fetch_index_tickers("IBRX")
    print(f"  IBOV: {len(ibov)} componentes | IBRX-100: {len(ibrx)} componentes")

    # Mapeia asset (nome abreviado) → ticker_completo
    asset_to_ticker: dict[str, str] = {}
    for ticker, asset in {**ibrx, **ibov}.items():  # IBOV sobrescreve IBRX
        asset_to_ticker[asset.upper().strip()] = ticker

    # Mapeia issuingCompany → ticker_completo
    issuer_to_ticker: dict[str, str] = {}
    for ticker, asset in {**ibrx, **ibov}.items():
        # O issuingCompany é os primeiros 4 chars do ticker (ex: PETR4 -> PETR)
        issuing = ticker[:4].upper()
        issuer_to_ticker[issuing] = ticker

    # Marca quais índices cada empresa está
    ibov_issuers = {t[:4] for t in ibov}
    ibrx_issuers = {t[:4] for t in ibrx}

    def resolve_ticker(row: pd.Series) -> tuple[str, str, str]:
        issuing = row["issuingCompany"].upper().strip()
        trading = row["tradingName"].upper().strip()

        indices_list = []
        if issuing in ibov_issuers:
            indices_list.append("IBOV")
        if issuing in ibrx_issuers:
            indices_list.append("IBRX")

        # Tenta pelo issuingCompany
        if issuing in issuer_to_ticker:
            return issuer_to_ticker[issuing], "index", ",".join(indices_list)

        # Tenta pelo tradingName
        if trading in asset_to_ticker:
            return asset_to_ticker[trading], "index", ",".join(indices_list)

        # Fallback: assume sufixo 3 (ON)
        return issuing + "3", "assumed", ",".join(indices_list)

    tickers, confidence, indices_col = zip(*b3_df.apply(resolve_ticker, axis=1))
    return list(tickers), list(confidence), list(indices_col)


def build_catalog() -> pd.DataFrame:
    """Gera o catálogo completo combinando B3 + CVM."""
    b3 = fetch_b3_companies()
    cvm = fetch_cvm_catalog()

    tickers, confidence, indices = build_ticker_map(b3)
    b3 = b3.copy()
    b3["ticker"] = tickers
    b3["ticker_confidence"] = confidence
    b3["indices"] = indices

    # Join com CVM pelo codeCVM
    cvm_slim = cvm[["CD_CVM", "DENOM_SOCIAL", "SETOR_ATIV", "CATEG_REG"]].rename(columns={
        "CD_CVM":     "codeCVM",
        "DENOM_SOCIAL": "nome_cvm",
        "SETOR_ATIV": "setor_cvm",
        "CATEG_REG":  "categ_reg",
    })
    df = b3.merge(cvm_slim, on="codeCVM", how="left")

    # Deduplica por CNPJ (mantém a primeira ocorrência — pode ter ON+PN)
    df = df.drop_duplicates(subset=["cnpj_fmt"]).copy()

    # Colunas finais
    result = df[[
        "ticker", "cnpj_fmt", "codeCVM", "companyName", "tradingName",
        "setor_cvm", "indices", "segment", "categ_reg", "ticker_confidence",
    ]].rename(columns={
        "cnpj_fmt":    "cnpj",
        "codeCVM":     "codigo_cvm",
        "companyName": "nome_cvm",
        "tradingName": "nome_b3",
        "segment":     "segment_b3",
    })

    result = result.sort_values("ticker").reset_index(drop=True)
    print(f"\nCatálogo: {len(result)} empresas únicas")
    idx_count = result["indices"].str.len().gt(0).sum()
    print(f"  Com ticker do índice (IBOV/IBRX): {idx_count}")
    print(f"  Ticker assumido (sufixo 3): {(result['ticker_confidence'] == 'assumed').sum()}")
    return result


def search_catalog(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Pesquisa por ticker, nome ou setor (case-insensitive)."""
    q = query.upper().strip()
    mask = (
        df["ticker"].str.upper().str.contains(q, na=False) |
        df["nome_b3"].str.upper().str.contains(q, na=False) |
        df["nome_cvm"].str.upper().str.contains(q, na=False) |
        df["setor_cvm"].str.upper().str.contains(q, na=False)
    )
    return df[mask]


def main():
    parser = argparse.ArgumentParser(description="Catálogo de empresas B3+CVM")
    parser.add_argument("--search", metavar="QUERY", help="Pesquisar por nome, ticker ou setor")
    parser.add_argument("--force", action="store_true", help="Força re-download mesmo que catalog já exista")
    args = parser.parse_args()

    if args.search:
        if not CATALOG_PATH.exists():
            print("Catálogo não encontrado — gerando primeiro...")
            df = build_catalog()
            df.to_csv(CATALOG_PATH, index=False)
        else:
            df = pd.read_csv(CATALOG_PATH, dtype=str)
        results = search_catalog(df, args.search)
        if results.empty:
            print(f"Nenhum resultado para '{args.search}'")
        else:
            print(f"{len(results)} resultado(s):\n")
            print(results[["ticker", "cnpj", "codigo_cvm", "nome_b3", "setor_cvm", "indices", "ticker_confidence"]].to_string(index=False))
        return

    if CATALOG_PATH.exists() and not args.force:
        print(f"Catálogo já existe: {CATALOG_PATH}")
        print("Use --force para re-gerar.")
        df = pd.read_csv(CATALOG_PATH, dtype=str)
        print(f"  {len(df)} empresas | atualizado em: {CATALOG_PATH.stat().st_mtime}")
        return

    df = build_catalog()
    df.to_csv(CATALOG_PATH, index=False)
    print(f"\nSalvo em: {CATALOG_PATH}")


if __name__ == "__main__":
    main()
