"""Etapa 7, DMPL: dividendos pagos (DFC, fato_padronizado) × declarados (DMPL 5.04.06 + 5.04.07) + Δ dividendos a pagar
(BPP 2.01.05.02.01 + 2.01.05.02.02 e contas próprias de dividendos/JCP a pagar no passivo, DFP do ano − DFP do
ano anterior). Somente leitura; DFPs do plano padrão.

    python st7_dmpl_dividendos.py
"""
import sqlite3
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
c = sqlite3.connect(f"file:{RAIZ / 'cvm_research.db'}?mode=ro", uri=True)
fato = {(r[0], r[1], r[2]): r[3] for r in c.execute(
    "SELECT cnpj_companhia, data_referencia, conceito, valor FROM fato_padronizado WHERE fonte = 'DFP' "
    "AND conceito IN ('dividendos_pagos', 'dividendos_declarados')")}
pagar = {}
for cnpj, data, vl in c.execute(
        "SELECT d.cnpj_companhia, d.data_referencia, SUM(d.vl_conta) FROM demonstrativos_contabeis d "
        "JOIN filings f ON f.cnpj_companhia = d.cnpj_companhia AND f.fonte = d.fonte AND f.tipo_doc = d.tipo_doc "
        " AND f.data_referencia = d.data_referencia AND f.versao = d.versao "
        "WHERE d.fonte = 'DFP' AND d.tipo_doc = 'BPP' AND d.ordem_exercicio = 'Último' "
        "AND (d.cd_conta IN ('2.01.05.02.01', '2.01.05.02.02') OR (d.st_conta_fixa = 'N' AND d.cd_conta LIKE '2.0_.%' "
        "     AND d.cd_conta NOT LIKE '2.03%' AND (lower(d.ds_conta) LIKE '%dividend%' OR lower(d.ds_conta) LIKE '%capital pr%' "
        "     OR lower(d.ds_conta) LIKE '%jcp%') AND lower(d.ds_conta) NOT LIKE '%receb%')) "
        "AND COALESCE(f.plano_contas, 'padrao') = 'padrao' "
        "GROUP BY 1, 2"):
    pagar[(cnpj, data)] = vl or 0.0
faixas, n, exemplos = Counter(), 0, []
for (cnpj, data, conc), dec in fato.items():
    if conc != "dividendos_declarados" or (cnpj, data, "dividendos_pagos") not in fato:
        continue
    ant = f"{int(data[:4]) - 1}{data[4:]}"
    if (cnpj, data) not in pagar or (cnpj, ant) not in pagar or not dec:
        continue
    pago = fato[(cnpj, data, "dividendos_pagos")]
    esperado = dec + (pagar[(cnpj, data)] - pagar[(cnpj, ant)])
    if not esperado:
        continue
    n += 1
    erro = abs(pago - esperado) / abs(esperado)
    faixa = "≤2%" if erro <= .02 else "2–10%" if erro <= .10 else "10–25%" if erro <= .25 else ">25%"
    faixas[faixa] += 1
    if faixa == ">25%" and len(exemplos) < 8:
        exemplos.append((cnpj, data, round(pago / 1e6), round(dec / 1e6), round(esperado / 1e6)))
print(f"DFPs com os três dados: {n}")
for f in ("≤2%", "2–10%", "10–25%", ">25%"):
    print(f"  {f:>7}: {faixas[f]:5} ({100 * faixas[f] / n:.1f}%)")
print("exemplos >25% (cnpj, data, pago, declarado, esperado; R$ mi):")
for e in exemplos:
    print("  ", e)
