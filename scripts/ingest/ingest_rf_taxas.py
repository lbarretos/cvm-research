"""
Taxas indicativas da ANBIMA (mercado secundário de debêntures e de CRI/CRA) → rf_taxas.

Baixa um arquivo por dia útil na janela pedida, só dos dias que ainda não estão no banco, e apaga o
que ficou mais velho que --reter dias. Feriado (arquivo inexistente) é pulado sem erro.

CRI/CRA não têm arquivo em URL fixa: o dataset público "CRIs e CRAs - Precificação ANBIMA" do
data.anbima.com.br (últimos cinco dias úteis, mercado inteiro) sai por um formulário, então é baixado à mão
e lido com --arquivo. Uma vez por semana basta para a janela não ter buraco. O arquivo também traz emissor,
devedor, série, emissão, vencimento e remuneração: código novo entra em rf_ativos (fonte 'anbima') e o
existente só tem os campos vazios preenchidos.

Uso:
  python ingest_rf_taxas.py                    # últimos 30 dias, guarda 30 dias
  python ingest_rf_taxas.py --dias 10 --reter 90
  python ingest_rf_taxas.py --so-deb
  python ingest_rf_taxas.py --arquivo ~/Downloads/certificados-recebiveis-precos-30-10-2026-15-39-35.xls
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


def cnpj_por_nome(conn) -> dict[str, str]:
    """Nome normalizado da securitizadora → CNPJ, pelas ofertas da CVM, só quando o nome casa com um CNPJ."""
    achados: dict[str, set] = {}
    for nome, cnpj in conn.execute("SELECT DISTINCT emissor_nome, emissor_cnpj FROM rf_ofertas "
                                   "WHERE emissor_nome IS NOT NULL AND emissor_cnpj IS NOT NULL"):
        achados.setdefault(F.norm(nome), set()).add(cnpj)
    return {n: c.pop() for n, c in achados.items() if len(c) == 1}


CAMPOS_CADASTRO = ["emissor_cnpj", "emissor_nome", "devedor_nome", "emissao", "serie", "data_vencimento",
                   "indexador", "remuneracao"]


def carregar_arquivo_cri_cra(conn, caminho) -> tuple[int, int]:
    """Planilha do dataset da ANBIMA → rf_taxas e rf_ativos. Devolve (taxas, títulos novos)."""
    taxas, cadastro = F.ler_anbima_data_cri_cra(caminho)
    upsert(conn, "rf_taxas", taxas, conflict="codigo,data")
    cnpjs = cnpj_por_nome(conn)
    existentes = {r[0] for r in conn.execute("SELECT codigo FROM rf_ativos")}
    hoje = date.today().isoformat()
    novos = []
    for c in cadastro:
        c["emissor_cnpj"] = cnpjs.get(F.norm(c["emissor_nome"]))
        if c["codigo"] in existentes:
            conn.execute(
                f"UPDATE rf_ativos SET {', '.join(f'{k} = COALESCE({k}, ?)' for k in CAMPOS_CADASTRO)}, "
                "atualizado_em = ? WHERE codigo = ?", [c[k] for k in CAMPOS_CADASTRO] + [hoje, c["codigo"]])
        else:
            novos.append({**c, "fonte": "anbima", "atualizado_em": hoje})
    upsert(conn, "rf_ativos", novos, conflict="codigo")
    conn.commit()
    return len(taxas), len(novos)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dias", type=int, default=30, help="janela de dias corridos a buscar (padrão 30)")
    p.add_argument("--reter", type=int, default=30, help="apaga taxas mais antigas que N dias (0 = não apaga)")
    p.add_argument("--so-deb", action="store_true")
    p.add_argument("--so-cri-cra", action="store_true")
    p.add_argument("--arquivo", action="append", default=[],
                   help="planilha do dataset 'CRIs e CRAs - Precificação ANBIMA' (repetível); não baixa nada")
    a = p.parse_args()

    conn = get_db()
    F.garantir_schema_rf(conn)
    if a.arquivo:
        for caminho in a.arquivo:
            n, novos = carregar_arquivo_cri_cra(conn, caminho)
            print(f"  {caminho}: {n} taxas, {novos} CRI/CRA novos em rf_ativos")
        return
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
