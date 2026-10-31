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
    "amort_divida": {
        "pagamento de instrumentos financeiros derivativos": "derivativo, não dívida",
        "liquidacao de instrumentos financeiros derivativos": "derivativo, não dívida",
        "recebimentos pagamentos de instrumentos financeiros derivativos": "derivativo, não dívida",
        "pagamento na liquidacao de instrumentos financeiros": "derivativo, não dívida",
        "amortizacao de instrumentos financeiros derivativos": "derivativo, não dívida",
        "pagamento de instrumentos financeiros derivativos exceto divida": "derivativo, não dívida",
        "pagamento recebimento de instrumentos financeiros derivativos": "derivativo, não dívida",
        "liquidacao de instrumentos financeiros derivativos hedge": "derivativo, não dívida",
        "pagamento por liquidacao de instrumentos financeiros derivativos": "derivativo, não dívida",
        "pagamento recebimento por liquidacao de instrumentos financeiros derivativos": "derivativo, não dívida",
        "pagamento recebimento de instrumentos financeiros": "derivativo, não dívida",
        "liquidacao de instrumento financeiro": "derivativo, não dívida",
        "pagamento recebimento de operacoes com derivativos financeiros": "derivativo, não dívida",
        "pagamentos instrumentos financeiros derivativos": "derivativo, não dívida",
        "liquidacao de operacoes de instrumentos financeiros derivativos": "derivativo, não dívida",
        "recebimento por liquidacao de instrumentos financeiros derivativos": "derivativo, não dívida",
        "liquidacao de instrumentos financeiros": "derivativo, não dívida",
        "recebimento na liquidacao de instrumentos financeiros derivativos principal": "derivativo, não dívida",
        "pagamento de instrumentos financeiros": "derivativo, não dívida",
        "recebimento pagamento por liquidacao de instrumentos financeiros derivativos": "derivativo, não dívida",
        "recebimento pagamento na liquidacao de instrumentos financeiros derivativos principal": "derivativo, não dívida",
        "pagamentos de passivo financeiro de clientes": "derivativo, não dívida",
        "pagamento custo de estruturacao debentures": "custo/comissão da dívida, não principal",
        "pagamentos de custos de emprestimos e financiamentos": "custo/comissão da dívida, não principal",
        "pagamento de custo de estruturacao de emprestimos e financiamentos e cri": "custo/comissão da dívida, não principal",
        "pagamento de custos de estruturacao de debentures": "custo/comissão da dívida, não principal",
        "pagamento de premio sobre liquidacao de debentures": "custo/comissão da dívida, não principal",
        "pagamento de custos de estruturacao de emprestimos e debentures": "custo/comissão da dívida, não principal",
        "pagamento de custo de estruturacao de emprestimos e financiamentos": "custo/comissão da dívida, não principal",
        "pagamento de custos de emissao de debentures": "custo/comissão da dívida, não principal",
        "amortizacao de custos com captacao de debentures": "custo/comissão da dívida, não principal",
        "custos de liquidacao de emprestimos e financiamentos": "custo/comissão da dívida, não principal",
        "pagamento de custos de estruturacao debentures": "custo/comissão da dívida, não principal",
        "pagamentos de comissoes sobre antecipacoes de debentures": "custo/comissão da dívida, não principal",
        "pagamento de comissao antecipacao de debentures": "custo/comissão da dívida, não principal",
        "pagamentos de custos": "custo/comissão da dívida, não principal",
        "pagamentos de antecipacao de recebiveis futuros comissoes": "custo/comissão da dívida, não principal",
        "pagamento de comissoes antecipacao de debentures": "custo/comissão da dívida, não principal",
        "pagamento de comissoes de antecipacao de debentures": "custo/comissão da dívida, não principal",
        "pagamento de comissao antecipacao de debentures e antecipacao de recebiveis": "custo/comissão da dívida, não principal",
        "pagamento de custo de estruturacao debentures": "custo/comissão da dívida, não principal",
        "pagamento de custo com captacao de debentures": "custo/comissão da dívida, não principal",
        "amortizacao de custo com captacao de debentures": "custo/comissão da dívida, não principal",
        "amortizacao de financiamento de impostos": "parcelamento de tributos, não dívida financeira",
        "pagamento de refinanciamento de impostos e contribuicoes principal": "parcelamento de tributos, não dívida financeira",
        "pagamento de refin de imp e cont principal": "parcelamento de tributos, não dívida financeira",
        "pagto de refinanc de impostos e cont principal": "parcelamento de tributos, não dívida financeira",
        "pagamento de refinanciamentos de impostos e contribuicao principal": "parcelamento de tributos, não dívida financeira",
        "amortizacao de financiamentos e impostos": "parcelamento de tributos, não dívida financeira",
        "amortizacao de emprestimos financiamentos e direitos de uso": "linha mista (dívida + arrendamento/direito de uso)",
        "amortizacao de emprestimos e financiamentos e direitos de uso": "linha mista (dívida + arrendamento/direito de uso)",
        "emissao de debentures": "linha líquida (entrada e saída), não amortização",
        "emissao liquidacao de debentures": "linha líquida (entrada e saída), não amortização",
        "emissao pagamento de debentures": "linha líquida (entrada e saída), não amortização",
        "emissao pagamento debentures": "linha líquida (entrada e saída), não amortização",
        "ingressos amortizacoes de debentures": "linha líquida (entrada e saída), não amortização",
        "ingressos amortizacoes debentures": "linha líquida (entrada e saída), não amortização",
        "recebimento pagamento de emprestimos empresas ligadas": "linha líquida (entrada e saída), não amortização",
        "recebimento pagamentos de emprestimos com partes relacionadas": "linha líquida (entrada e saída), não amortização",
        "recebimentos e pagamentos a partes relacionadas": "linha líquida (entrada e saída), não amortização",
        "recebimentos e pagamentos de emprestimos de partes relacionadas": "linha líquida (entrada e saída), não amortização",
        "recebimentos pagamentos de emprestimos com partes relacionadas": "linha líquida (entrada e saída), não amortização",
        "amortizacao de emprestimos financiamentos e diretos de uso": "linha mista (dívida + arrendamento/direito de uso)",
        "amortizacao de emprestimos financiamentos cri e direitos de uso": "linha mista (dívida + arrendamento/direito de uso)",
        "pagamentos de principal de emprestimos financiamentos debentures derivativos e leasing": "linha mista (dívida + arrendamento/direito de uso)",
        "amortizacoes de principal de emprestimos e financiamentos concedidos intragrupo": "empréstimo concedido (ativo)",
        "captacao liquidacao de emprestimos": "captação e liquidação na mesma linha",
    },
    "capt_divida": {
        "recebimento de emprestimos para partes relacionadas": "devolução de empréstimo concedido",
        "recebimento de emprestimo para parte relacionada": "devolução de empréstimo concedido",
        "captacoes de passivo financeiro de clientes": "passivo com clientes, não dívida",
        "valores pagos na emissao de debentures": "custo da emissão",
        "comissao sobre captacao de debentures": "custo da emissão",
        "gasto com emissao de acao e debentures": "custo da emissão",
        "recebimento de reembolso seguros antecipados refinanciamento": "reembolso de seguro",
        "recebimento de reembolso seguros antecipados refinanciamento celse": "reembolso de seguro",
        "captacao pagto de emprestimos e financiamentos outros": "captação e pagamento na mesma linha",
        "captacao amortizacao de emprestimos e financiamentos arrendamentos financeiros e debentures": "captação e amortização na mesma linha",
        "ingresso de financiamento por arrendamento": "linha mista (dívida + arrendamento/direito de uso)",
        "ingresso de financiamento arrendado": "linha mista (dívida + arrendamento/direito de uso)",
        "captacao de emprestimos financiamentos e debentures risco sacado direito de uso e cessao de credi": "linha mista (dívida + arrendamento/direito de uso)",
        "captacao de emprestimo financiamentos e debentures risco sacado direito de uso e cessao de credit": "linha mista (dívida + arrendamento/direito de uso)",
        "novos emprestimos e financiamentos arrendamentos financeiros a pagar e debentures": "linha mista (dívida + arrendamento/direito de uso)",
        "novos emprestimos e financiamentos arrendamentos financeiros e debentures": "linha mista (dívida + arrendamento/direito de uso)",
        "captacao de emprestimos e financiamentos deben arrendamentos e risco sacado": "linha mista (dívida + arrendamento/direito de uso)",
        "captacao de emprestimos financiamentos debentures e arrendam mercantil": "linha mista (dívida + arrendamento/direito de uso)",
    },
    "juros_pagos": {
        "pagamento de principal e juros debitos concessoes": "principal e juros na mesma linha",
        "pagamento do principal e juros cemig": "principal e juros na mesma linha",
        "pagamento de principal e juros sobre emprestimos e financiamentos": "principal e juros na mesma linha",
        "pagamento de emprestimos financiamentos e debentures principal e juros": "principal e juros na mesma linha",
        "pagamento de emprestimos inclui juros": "principal e juros na mesma linha",
        "pgto de emprestimos inclui juros": "principal e juros na mesma linha",
        "juros pagos e emprestimos amortizados": "principal e juros na mesma linha",
        "amortizacao de debentures e juros pagos": "principal e juros na mesma linha",
        "emprestimos financiamentos e debentures pagamentos de principal e juros": "principal e juros na mesma linha",
        "emprestimos financiamentos debentures e notas comerciais pagamentos de principal e juros": "principal e juros na mesma linha",
        "pagamento de emprestimos e debentures inclui juros": "principal e juros na mesma linha",
        "pagamento de debentures principal juros": "principal e juros na mesma linha",
        "pagamento de emprestimos e financiamentos principal juros": "principal e juros na mesma linha",
        "pagamento de emprestimos financiamentos e debentures principal juros": "principal e juros na mesma linha",
        "pagamento de juros amortiz e partic resultado debentures": "principal e juros na mesma linha",
        "financiamentos e juros pagos": "principal e juros na mesma linha",
        "juros de arredamento pagos": "arrendamento, não juros de dívida",
        "pagamento de juros leasing": "arrendamento, não juros de dívida",
        "pagamento de juros de alugueis ifrs 16": "arrendamento, não juros de dívida",
        "emprestimos financiamentos debentures e leasing pagamentos de juros": "arrendamento, não juros de dívida",
        "emprestimos financiamentos debentures e leasing pagamento de juros": "arrendamento, não juros de dívida",
        "emprestimos financiamentos debentures notas promissorias e arred mercantil pagamento de juros": "arrendamento, não juros de dívida",
        "pagamento de juros e principal leasing": "arrendamento, não juros de dívida",
        "variacoes cambiais pagas": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento encargos da reserva global de reversao": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de encargos da reserva global de reversao": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de parcelamento de encargos setoriais": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de parcelamentos de tributos": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de derivativos hedge de valor justo": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de debentures": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de emprestimos": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de financiamentos": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamento de emprestimos financiamentos": "não é juros (veio pelo voto ou é outro encargo)",
        "pagamentos de antecipacao de recebiveis futuros": "não é juros (veio pelo voto ou é outro encargo)",
        "reducao aumento nos passivos pagamento de juros": "não é juros (veio pelo voto ou é outro encargo)",
    },
    "dividendos_pagos": {
        "pagamento de derivativos": "não é dividendo pago",
        "constituicao de juros sobre capital proprio": "não é dividendo pago",
        "reversao de dividendos": "não é dividendo pago",
        "distribuicao de dividendos as contas de reservas de lucros": "não é dividendo pago",
        "pagamento de dividendos ou aquisicao de participacao de nao controladores": "não é dividendo pago",
        "aumento de capital distribuicao de dividendos": "não é dividendo pago",
        "participacao dos acionistas nao controladores": "não é dividendo pago",
    },
    "ir_pago": {
        "imposto de renda na fonte do juros sobre capital proprio pago": "IRRF sobre JCP, não IR sobre o lucro",
        "imposto de renda na fonte do juros sobre capital proprio creditado": "IRRF sobre JCP, não IR sobre o lucro",
        "imposto de renda na fonte do juros sobre capital propriopago": "IRRF sobre JCP, não IR sobre o lucro",
        "pagamento de refin de impostos e contribuicoes principal": "parcelamento de tributos, não dívida financeira",
        "pagamento de refin de impostos e contribuicao social": "parcelamento de tributos, não dívida financeira",
        "pagamento de refin de impostos e contribuicao principal": "parcelamento de tributos, não dívida financeira",
    },
    "capex_imob": {
        "juros capitalizados no ativo imobilizado": "juros, não capex",
        "aplicacao imobilizado por combinacao de negocios": "M&A",
        "participacoes financeira do consumidor no imobilizado": "contribuição de cliente",
    },
    "capex_intang": {
        "aquisicao intangivel por alienacao de acoes tesouraria": "não caixa",
        "aquisicao intangivel por alienacao de acoes em tesouraria": "não caixa",
        "obrigacao por aquisicao de investimentos intangivel": "M&A",
        "agio aquisicao de investimentos intangivel": "M&A",
        "baixas em intangivel": "baixa",
    },
    "capex_conjunto": {
        "aquisicao de imobilizado e intangivel agio e mais valia": "inclui ágio/mais-valia (M&A)",
        "aquisicoes de imobilizado e intangivel agio e mais valia": "inclui ágio/mais-valia (M&A)",
        "receita na aienacao de imobilizado e intangivel": "venda",
        "ganho no ativo imobilizado e intangivel": "ganho",
        "adicao de imobilizado intangivel na incorporacao": "não caixa",
    },
    "da_ex_ppa": {
        "amortizacao de custo de captacao": "custo de captação da dívida, não D&A",
        "amortizacao dos custos de captacao": "custo de captação da dívida, não D&A",
        "amortizacao do custo de captacao": "custo de captação da dívida, não D&A",
        "amortizacao de gastos na captacao de recursos": "custo de captação da dívida, não D&A",
        "amortizacao de gastos incorridos na captacao de recursos": "custo de captação da dívida, não D&A",
        "amortizacao custo captacao": "custo de captação da dívida, não D&A",
        "amortizacao de custos de captacao": "custo de captação da dívida, não D&A",
        "amortizacao de gastos na captacao de recurso": "custo de captação da dívida, não D&A",
        "depreciacao ifrs 16": "direito de uso: vai para da_direito_uso",
        "depreciacao de direitos de uso": "direito de uso: vai para da_direito_uso",
        "depreciacao de direitodos de uso": "direito de uso: vai para da_direito_uso",
        "amortizacao de direito e uso": "direito de uso: vai para da_direito_uso",
        "depreciacao de direito e uso": "direito de uso: vai para da_direito_uso",
        "depreciacao e amortizacao ifrs 16": "direito de uso: vai para da_direito_uso",
        "depreciacao amortizacao e impairment": "inclui impairment",
        "depreciacao amortizacao e impairment de ativos": "inclui impairment",
        "depreciacoes amortizacoes e desvalorizacao impairment de ativos": "inclui impairment",
        "depreciacao e amortizacao e impairment": "inclui impairment",
        "outros ajustes depreciacao tributos retidos": "não é D&A",
        "linearizacao de receitas amortizadas": "não é D&A",
        "amortizacao de receita diferida subvencao cde": "não é D&A",
        "amortizacao plano de stock options": "não é D&A",
        "amortizacao do fundo criatec iii": "não é D&A",
        "mudanca no valor justo e amortizacao da mais ou menos valia dos ativos biologicos": "não é D&A",
        "resultado de equivalencia patrimonial e amortizacao do ppa": "não é D&A",
        "amortizacao de aquisicoes com desconto de contingencias e provisao de responsabilidade dos vendedore": "não é D&A",
    },
    "da_direito_uso": {
        "amortizacao de direito de uso e custo de transacao das debentures": "mistura custo da dívida",
        "amortizacao do custo de transacao das debentures": "custo da dívida",
        "variacao sobre arrendamentos": "não é D&A",
    },
    "da_ppa": {
        "prov p perdas de investimentos amortizacao de agio": "inclui provisão para perdas",
        "amortizacao do custo de captacao agio e desagio": "inclui custo da dívida",
        "amortizacao do custo de captacao agio e desagio nota 17 2": "inclui custo da dívida",
        "reversao do ajuste a valor presente e amortizacao de contrato arrendamento": "AVP/arrendamento",
        "amortizacao do direito da concessao gerado em aquisicoes e perda na alienacao de invest maas": "inclui perda na alienação",
        "amortizacao do valor justo de contas a receber vinculadas a concessao": "não é D&A",
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
        "amortizacao de financiamentos e direito de uso": "mistura dívida e arrendamento",
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
