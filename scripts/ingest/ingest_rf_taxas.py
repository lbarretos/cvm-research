"""
Taxas indicativas da ANBIMA (mercado secundário de debêntures e de CRI/CRA) → rf_taxas.

Baixa um arquivo por dia útil na janela pedida, só dos dias que ainda não estão no banco, e apaga o
que ficou mais velho que --reter dias. Feriado (arquivo inexistente) é pulado sem erro.

Uso:
  python ingest_rf_taxas.py                    # últimos 30 dias, guarda 30 dias
  python ingest_rf_taxas.py --dias 10 --reter 90
  python ingest_rf_taxas.py --so-deb
Layouts: ver rf_fontes.py (`--verificar`).
"""
import argparse
import sys
from datetime import date, timedelta

import httpx

import rf_fontes as F
from utils import _http_get, get_db, upsert


def dias_uteis(fim: date, dias: int) -> list[date]:
    """Dias de semana em (fim − dias, fim], do mais antigo ao mais recente. Feriado sai pelo 404."""
    return [d for d in (fim - timedelta(days=i) for i in range(dias - 1, -1, -1)) if d.weekday() < 5]


def ja_carregados(conn, fonte: str) -> set[str]:
    """Datas já presentes para a fonte: DEB pelos códigos de debênture, CRI_CRA pelos de CRI/CRA."""
    tipos = ("DEB",) if fonte == "DEB" else ("CRI", "CRA")
    q = f"SELECT DISTINCT data FROM rf_taxas WHERE tipo IN ({','.join('?' * len(tipos))})"
    return {r[0] for r in conn.execute(q, tipos)}


def baixar_dia(fonte: str, dia: date) -> list[dict] | None:
    url = F.url_anbima(fonte, dia)
    try:
        r = _http_get(url, timeout=60)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None   # feriado ou ainda não publicado
        raise
    return F.parse_anbima(r.content, dia, "DEB" if fonte == "DEB" else "OUTRO")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dias", type=int, default=30, help="janela de dias corridos a buscar (padrão 30)")
    p.add_argument("--reter", type=int, default=30, help="apaga taxas mais antigas que N dias (0 = não apaga)")
    p.add_argument("--so-deb", action="store_true")
    p.add_argument("--so-cri-cra", action="store_true")
    a = p.parse_args()

    conn = get_db()
    fontes = ["DEB"] * (not a.so_cri_cra) + ["CRI_CRA"] * (not a.so_deb and bool(F.URL_ANBIMA_CRI_CRA))
    if not a.so_deb and not F.URL_ANBIMA_CRI_CRA:
        print("  CRI/CRA: fonte desligada (RF_URL_ANBIMA_CRI_CRA vazio)")
    erros, lidos = 0, 0
    for fonte in fontes:
        feitos = ja_carregados(conn, fonte)
        for dia in dias_uteis(date.today(), a.dias):
            if dia.isoformat() in feitos:
                continue
            try:
                linhas = baixar_dia(fonte, dia)
            except Exception as e:
                print(f"  {fonte} {dia}: ERRO {e}", file=sys.stderr)
                erros += 1
                continue
            if linhas is None:
                print(f"  {fonte} {dia}: sem arquivo (feriado?)")
                continue
            upsert(conn, "rf_taxas", linhas, conflict="codigo,data")
            lidos += 1
    if a.reter:
        corte = (date.today() - timedelta(days=a.reter)).isoformat()
        n = conn.execute("DELETE FROM rf_taxas WHERE data < ?", (corte,)).rowcount
        conn.commit()
        print(f"  rf_taxas: {n} linhas anteriores a {corte} apagadas")
    print(f"{lidos} arquivo(s) lido(s), {erros} erro(s)")
    if erros and not lidos:
        sys.exit(1)


if __name__ == "__main__":
    main()
