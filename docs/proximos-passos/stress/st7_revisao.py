"""Revisão da Etapa 7: tudo o que entra nos fatos de um conceito, agrupado por nome de linha (sem amostra).

Roda taxonomia.fatos_da_empresa em todas as empresas (somente leitura) e lista, para cada conceito pedido, os
nomes normalizados das células que entraram num fato, com o número de células, de empresas e o valor somado.
`ERROS` guarda a revisão (nome → motivo): a precisão sai em células e em valor absoluto.

    python st7_revisao.py recompra arrend_pago divida_liquida_fluxo [--listar]
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "scripts" / "analysis"))
sys.path.insert(0, str(RAIZ / "scripts" / "ingest"))

import taxonomia as T  # noqa: E402
from consistency_utils import latest_rows, normalize_text  # noqa: E402

# Revisão por nome normalizado (Claude, 2026-10-30; não é revisão de analista). Um nome aqui é erro do conceito.
_OPCOES = "exercício de opções / ILP com tesouraria: entrega de ações, não recompra"
ERROS: dict[str, dict[str, str]] = {
    "divida_liquida_fluxo": {
        "financiamentos com empresas ligadas liquido": "mútuo com partes relacionadas, não dívida",
        "financiamentos com empresas coligadas e controladas em conjunto liquido": "mútuo com partes relacionadas",
        "emissao de debentures liquida de gastos com captacao": "captação (líquida de custo), não fluxo líquido",
        "emissao de debentures liquida de gastos com emissao": "captação (líquida de custo), não fluxo líquido",
    },
    "recompra": {
        "utilizacao de acoes em tesouraria pelo exercicio de opcoes de compra de acoes": _OPCOES,
        "utilizacao de acoes em tesouraria decorrente de exercicio de opcoes de acoes": _OPCOES,
        "utilizacao de acoes em tesouraria pelo exercicio de opcoes de opcoes de compra de opcoes": _OPCOES,
        "exercicio das opcoes de acoes com acoes em tesouraria liquido": _OPCOES,
        "exercicio dos programas de incentivo de longo prazo com acoes em tesouraria": _OPCOES,
        "pagamento de ilp com acoes em tesouraria": _OPCOES,
        "pagamento de ilp com acoes de acoes": _OPCOES,
        "pagamento de acoes em tesouraria e exercicio opcoes stock options": _OPCOES,
        "acoes em tesouraria vendidas": "venda de tesouraria",
        "venda de acoes em tesouraria": "venda de tesouraria",
        "venda de acoes em tesouraria pelo exercicio de opcoes de compra de acoes": "venda de tesouraria",
        "venda de acoes em tesouraria pelo exercicio de opcoes de opcoes de compra de opcoes": "venda de tesouraria",
        "alientacao de acoes em tesouraria": "alienação de tesouraria (com erro de digitação)",
        "recompra de cessao de recebiveis": "recompra de recebíveis cedidos, não de ações",
        "aquisicao de acoes de controladas e recompra de acoes": "mistura aquisição de participação com recompra",
        "aporte de capital e recompra de acoes de investidas": "ações de investidas, não da companhia",
    },
    "arrend_pago": {
        "amortizacao de empres e financi arrends deben e risco sacado a pagar montadoras": "mistura dívida e arrendamento",
        "pagamentos de emprest financ arrend a pagar e arrend dir de uso": "mistura dívida e arrendamento",
        "amortizacao de juros de financiamento e arrendamentos": "mistura dívida e arrendamento",
        "adicoes de arrendamentos mercantil": "adição (não caixa)",
        "adicao ao passivo de arrendamento": "adição (não caixa)",
        "passivo de arrendamento constituicoes": "adição (não caixa)",
        "ganho de arrendamento": "ganho (não caixa)",
        "baixa de passivo por arrendamento": "baixa (não caixa)",
        "amort de empres e financ arrend mercan a pgr arrend p direito de uso deben e risco sac": "mistura dívida e arrendamento",
        "pagamento de emprest financ arrend mercant a pagar arrend dir de uso": "mistura dívida e arrendamento",
        "amort de emp e financiamentos arrend debent e risco sacado a pagar montadoras": "mistura dívida e arrendamento",
        "amortizacao de emprestimos e financiamentos arrendamentos debentures e risco sacado": "mistura dívida e arrendamento",
        "amort de empre e financi arrend deben e risco sacado a pagar montadoras": "mistura dívida e arrendamento",
        "pag de emprestimos financ arrend mercant a pagar e arrend p direito de uso": "mistura dívida e arrendamento",
        "pagamentos de emprest financ e deb arrend a pagar e arrend por direito de uso": "mistura dívida e arrendamento",
        "pagamentos de emprest financ e deb risco sacado e arrendamentos": "mistura dívida e arrendamento",
        "amort de emp e financiamentos arrend debent arrendamentos e risco sacado a pagar": "mistura dívida e arrendamento",
        "captacao de arrendamentos": "entrada, não pagamento",
        "contratacao de operacoes de arrendamento mercantil": "contratação (não caixa)",
        "passivo de arrendamento constituicao": "adição (não caixa)",
        "amortizacao de pre pagamento": "pré-pagamento, não arrendamento (veio pelo voto)",
    },
}


def coletar(conceitos: set[str]):
    conn = sqlite3.connect(f"file:{RAIZ / 'cvm_research.db'}?mode=ro", uri=True)
    por = {c: defaultdict(lambda: [0, set(), 0.0]) for c in conceitos}
    for (cnpj,) in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj").fetchall():
        df = latest_rows(conn, cnpj=cnpj)
        ids = {(r[0], r[1], r[2]): r[3] for r in conn.execute(
            "SELECT fonte, data_referencia, cd_conta, linha_id FROM linha_empresa "
            "WHERE cnpj_companhia = ? AND tipo_doc = 'DFC_MI'", (cnpj,))}
        contrib = []
        T.fatos_da_empresa(df, ids, cnpj, contribuicoes=contrib)
        for _f, _d, _cd, ds, c, v in contrib:
            if c in por:
                x = por[c][normalize_text(ds or "")]
                x[0] += 1
                x[1].add(cnpj)
                x[2] += abs(v)
    return por


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conceitos", nargs="+")
    ap.add_argument("--listar", action="store_true", help="imprime todos os nomes")
    a = ap.parse_args()
    por = coletar(set(a.conceitos))
    for c in a.conceitos:
        nomes = por[c]
        erros = ERROS.get(c, {})
        n = sum(x[0] for x in nomes.values())
        vt = sum(x[2] for x in nomes.values()) or 1
        ne = sum(x[0] for k, x in nomes.items() if k in erros)
        ve = sum(x[2] for k, x in nomes.items() if k in erros)
        print(f"\n=== {c}: {n} células, {len(nomes)} nomes; erros {ne} células ({100 * ne / max(n, 1):.1f}%), "
              f"{100 * ve / vt:.1f}% do valor → precisão {100 * (1 - ne / max(n, 1)):.1f}%")
        if a.listar:
            for k, (q, emp, v) in sorted(nomes.items(), key=lambda kv: -kv[1][0]):
                marca = "ERRO " + erros[k] if k in erros else ""
                print(f"  {q:>5} {len(emp):>3} {v / 1e6:>12,.0f} mi  {k}  {marca}")


if __name__ == "__main__":
    main()
