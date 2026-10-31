"""
Etapa 7: taxonomia canônica (camada L2). Conceitos comparáveis entre empresas, a partir das linhas
criadas pela empresa (`N`) da DFC e das contas fixas (`S`) das demonstrações do plano padrão.

Fluxo (por empresa):
  1. cada linha folha `N` da DFC é rotulada por REGRAS (regex sobre o nome normalizado + prefixo do pai +
     exclusões + sinal esperado). Uma linha cai em no máximo um conceito (CONFLITO vira "sem conceito");
  2. o rótulo é votado por **linha econômica** (Etapa 6, `linha_empresa.linha_id`): o conceito majoritário
     da linha vale para todos os filings dela, inclusive aqueles em que o nome variou demais para a regra;
  3. `fato_padronizado`: soma por (filing, conceito), mais os conceitos derivados (`da_total`, `capex_total`)
     e os de contas S (`receita_liquida`, `cfo`…). Cada fato carrega a checagem e só é `publicado` se passar.

Tabelas: conceito, linha_conceito, fato_padronizado (schema.sql / migração 2026-10-16_taxonomia.sql).
Não implementado (ver docs/proximos-passos/07-taxonomia-canonica.md): modelo supervisionado, fila de
revisão humana e demonstrações individuais. A DMPL entra pelas contas fixas (tabela `dmpl`, coluna 'pl_consolidado'):
dividendos e JCP declarados, aumentos de capital e ações em tesouraria adquiridas.

    python taxonomia.py --full               # base inteira
    python taxonomia.py --cnpj 84.429.695/0001-11
"""
import argparse
import re
from collections import Counter, defaultdict

import pandas as pd

from consistency_utils import get_db, latest_rows, normalize_text

TOL_DA = 0.02          # D&A da DFC contra a DVA 7.04.01
MAJORITARIO = 0.8      # parcela mínima de votos para o conceito valer para a linha econômica inteira

# conceito: (nome, tipo_doc, pai, sinal esperado: +1 entrada/adição, -1 saída, 0 qualquer, derivado?)
CONCEITOS = {
    "da_ex_ppa":            ("Depreciação, amortização e exaustão (sem direito de uso nem mais-valia)", "DFC_MI", "da_total", +1, False),
    "da_direito_uso":       ("Depreciação de direito de uso", "DFC_MI", "da_total", +1, False),
    "da_ppa":               ("Amortização de mais-valia, ágio, concessão e contratos de aquisição", "DFC_MI", "da_total", +1, False),
    "da_total":             ("D&A total (gabarito: DVA 7.04.01)", "DFC_MI", None, +1, True),
    "capex_imob":           ("Aquisição de imobilizado", "DFC_MI", "capex_total", -1, False),
    "capex_intang":         ("Aquisição de intangível", "DFC_MI", "capex_total", -1, False),
    "capex_conjunto":       ("Aquisição de imobilizado e intangível (linha única)", "DFC_MI", "capex_total", -1, False),
    "capex_total":          ("Capex (imobilizado + intangível)", "DFC_MI", None, -1, True),
    "dividendos_pagos":     ("Dividendos e JCP pagos", "DFC_MI", None, -1, False),
    "juros_pagos":          ("Juros pagos (caixa)", "DFC_MI", None, -1, False),
    "capt_divida":          ("Captação de dívida", "DFC_MI", None, +1, False),
    "amort_divida":         ("Amortização de dívida", "DFC_MI", None, -1, False),
    "divida_liquida_fluxo": ("Captação e amortização de dívida em linha única (líquido)", "DFC_MI", None, 0, False),
    "arrend_pago":          ("Pagamento de arrendamento", "DFC_MI", None, -1, False),
    "recompra":             ("Recompra de ações", "DFC_MI", None, -1, False),
    "ir_pago":              ("IR e CS pagos", "DFC_MI", None, -1, False),
    # contas fixas (S) do plano padrão
    "receita_liquida":      ("Receita líquida", "DRE", None, 0, False),
    "resultado_bruto":      ("Resultado bruto", "DRE", None, 0, False),
    "ebit":                 ("Resultado antes do resultado financeiro e dos tributos", "DRE", None, 0, False),
    "lucro_liquido":        ("Lucro líquido consolidado do período", "DRE", None, 0, False),
    "cfo":                  ("Caixa das atividades operacionais", "DFC_MI", None, 0, False),
    "cfi":                  ("Caixa das atividades de investimento", "DFC_MI", None, 0, False),
    "cff":                  ("Caixa das atividades de financiamento", "DFC_MI", None, 0, False),
    "variacao_caixa":       ("Aumento (redução) de caixa e equivalentes", "DFC_MI", None, 0, False),
    "caixa_final":          ("Caixa e equivalentes no fim do período", "DFC_MI", None, 0, False),
    "ativo_total":          ("Ativo total", "BPA", None, 0, False),
    "patrimonio_liquido":   ("Patrimônio líquido consolidado", "BPP", None, 0, False),
    # DMPL (contas fixas 5.04.xx, coluna 'pl_consolidado' da tabela dmpl)
    "dividendos_declarados": ("Dividendos e JCP declarados (DMPL 5.04.06 + 5.04.07)", "DMPL", None, -1, False),
    "aumento_capital":      ("Aumentos de capital (DMPL 5.04.01; capitalização de reservas se anula no PL)", "DMPL", None, 0, False),
    "recompra_dmpl":        ("Ações em tesouraria adquiridas (DMPL 5.04.04)", "DMPL", None, -1, False),
}
CONTAS_S = {"receita_liquida": ("DRE", "3.01"), "resultado_bruto": ("DRE", "3.03"), "ebit": ("DRE", "3.05"),
            "lucro_liquido": ("DRE", "3.11"), "cfo": ("DFC_MI", "6.01"), "cfi": ("DFC_MI", "6.02"),
            "cff": ("DFC_MI", "6.03"), "variacao_caixa": ("DFC_MI", "6.05"), "caixa_final": ("DFC_MI", "6.05.02"),
            "ativo_total": ("BPA", "1"), "patrimonio_liquido": ("BPP", "2.03")}

# conceito: (prefixos aceitos do código, padrão, exclusão)
_DEBITO = r"(emprest|financ|debent|nota|bond|cedula|cri|cra)"
REGRAS = {
    "da_ex_ppa": (("6.01.01",), r"\b(deprec|amortiz|exaust)",
                  r"(emprest|financ|debent|juros|agio|mais.?valia|custo de transac|direito de uso|arrend|concess|"
                  r"contrato|combinacao|carteira|marca|goodwill|ganho|perda|despesas antecipadas|stand|comerciais|reversao|"
                  r"credito|pis|cofins)"),
    "da_direito_uso": (("6.01.01",), r"(deprec|amortiz).*(direito de uso|arrend)|direito de uso.*(deprec|amortiz)",
                       r"(baixa|reversao|ganho|perda)"),
    "da_ppa": (("6.01.01",), r"(deprec|amortiz).*(mais.?valia|agio|goodwill|concess|contrato|combinacao|carteira|marca)",
               r"(emprest|financ|debent|custo de transac|juros)"),
    "capex_imob": (("6.02",), r"(aquisic|adic|compra|investimento|aplica|no|em).*imobiliz|^imobilizado$|ativo fixo|bens do ativo",
                   r"(venda|alienac|recebim|baixa|intang)"),
    "capex_intang": (("6.02",), r"(aquisic|adic|compra|investimento|aplica|no|em).*intang|^intangivel$",
                     r"(venda|alienac|recebim|imobiliz)"),
    "capex_conjunto": (("6.02",), r"(imobiliz.*intang|intang.*imobiliz)", r"(venda|alienac|recebim|baixa|outros)"),
    "dividendos_pagos": (("6.03",), r"(dividend|juros sobre (o )?capital|jcp)", r"(recebid|receb|a pagar)"),
    "juros_pagos": (("6.01.02", "6.01.03", "6.03"),
                    r"(juros|encargos).*(pag|liquid)|pagamento.*(juros|encargos)",
                    r"(capital proprio|sobre (o )?capital|recebid|arrend|direito de uso|provisionad|apropriad|incorrid|"
                    r"salario|ferias|encargos (sociais|trabalhistas)|folha|a pagar)"),
    "capt_divida": (("6.03",), rf"(captac|obtenc|ingresso|emissao|recebimento|novos|contratac).*{_DEBITO}",
                    r"(custo|custos|derivativ|instrumentos financeiros|despesa)"),
    "amort_divida": (("6.03",), rf"(amortiz|pagamento|liquidac|quitac).*{_DEBITO}", r"(juros|encargos|arrend|direito de uso|dividend)"),
    "divida_liquida_fluxo": (("6.03",), rf"{_DEBITO}.*(captac|amortiz|pagamento).*(captac|amortiz|pagamento)|"
                                        rf"(captac|ingresso).*(e|ou).*(amortiz|pagamento)|"
                                        rf"{_DEBITO}.*\bliquid[oa]s?\b|\bliquid[oa]s?\b.*{_DEBITO}|aumento.*reducao.*{_DEBITO}",
                             r"(liquidad|liquidac|instrumentos? financeiros?|recebid|atividade|caixa|recursos|aumento de capital|subscri|"
                             r"partes relacionadas|descontinuad|mantidos|investimento|custo|despesa|hedge|swap|captacoes$)"),
    "arrend_pago": (("6.03",), r"(arrend|direito de uso|lease|locac)",
                    r"(sale|leaseback|recebid|ingresso|entrada|obtido|captac|emprestimos|avp)"),
    "recompra": (("6.03",), r"(recompra|aquisicao de acoes|acoes em tesouraria)", r"(venda|alienac|debent|bond|nota|titulo|resultado|cancelamento|ganho|perda)"),
    "ir_pago": (("6.01",), r"(imposto de renda|ir e cs|irpj|contribuicao social).*(pag|recolh)|"
                           r"(pag|recolh).*(imposto de renda|ir e cs|irpj|contribuicao social|tributos sobre o lucro)",
                r"(a recolher|a pagar|provisao|provisoes|diferid|compensac|a recuperar|refinanc|parcelamento|refis)"),
}
# a regra mais específica vence a geral em vez de gerar conflito
ESPECIFICA_SOBRE = {"divida_liquida_fluxo": {"capt_divida", "amort_divida"},
                    "capex_conjunto": {"capex_imob", "capex_intang"},
                    "da_direito_uso": {"da_ex_ppa"}, "da_ppa": {"da_ex_ppa"}}
_COMP = {k: (p, re.compile(pat), re.compile(exc) if exc else None) for k, (p, pat, exc) in REGRAS.items()}

DDL = """
CREATE TABLE IF NOT EXISTS conceito (
    conceito  TEXT PRIMARY KEY,
    nome      TEXT NOT NULL,
    tipo_doc  TEXT NOT NULL,
    pai       TEXT,
    sinal     INTEGER NOT NULL,
    derivado  INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS linha_conceito (
    cnpj_companhia TEXT NOT NULL,
    tipo_doc       TEXT NOT NULL,
    linha_id       TEXT NOT NULL,
    conceito       TEXT NOT NULL,
    metodo         TEXT NOT NULL,          -- 'regra'
    confianca      REAL NOT NULL,          -- parcela dos votos dos filings classificados
    n_filings      INTEGER NOT NULL,
    PRIMARY KEY (cnpj_companhia, tipo_doc, linha_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS fato_padronizado (
    cnpj_companhia  TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    data_referencia TEXT NOT NULL,
    periodo_ini     TEXT NOT NULL,         -- 'NA' em balanço
    periodo_fim     TEXT NOT NULL,
    conceito        TEXT NOT NULL,
    valor           REAL,
    n_linhas        INTEGER NOT NULL,
    metodo          TEXT NOT NULL,         -- 'S' | 'regra' | 'derivado'
    confianca       REAL NOT NULL,
    checagem        TEXT NOT NULL,         -- ok | ok_<definição alternativa da DVA> | sem_gabarito | divergente | sinal_trocado | maior_que_pai
    publicado       INTEGER NOT NULL,      -- 1 só se a checagem passou
    PRIMARY KEY (cnpj_companhia, fonte, data_referencia, periodo_ini, periodo_fim, conceito)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_fato_conceito ON fato_padronizado (conceito, data_referencia);
"""


def classificar(cd: str, dsn: str, vl=None) -> str | None:
    """Conceito de uma linha N da DFC (pelo código e pelo nome normalizado), ou None.
    Com `vl`, linha de sinal contrário ao esperado fica sem conceito: "ações em tesouraria" positiva é
    venda/exercício de opção, não recompra, e o mesmo nome muda de sentido conforme o sinal."""
    achados = {k for k, (pref, pat, exc) in _COMP.items()
               if cd.startswith(pref) and pat.search(dsn) and not (exc and exc.search(dsn))}
    for forte, fracos in ESPECIFICA_SOBRE.items():
        if forte in achados:
            achados -= fracos
    if len(achados) != 1:
        return None
    k = next(iter(achados))
    esp = CONCEITOS[k][3]
    if vl is not None and esp and vl and (vl > 0) != (esp > 0):
        return None
    return k


def _folhas(codigos) -> set:
    cs = sorted(codigos)
    return {c for i, c in enumerate(cs) if not (i + 1 < len(cs) and cs[i + 1].startswith(c + "."))}


def _periodo(g: pd.DataFrame):
    """(periodo_ini, periodo_fim) do filing: o acumulado (menor início) no ITR."""
    ini = g["periodo_ini"].min() if (g["periodo_ini"] != "NA").any() else "NA"
    return ini, g["periodo_fim"].max()


def votar(linhas: pd.DataFrame) -> dict:
    """linhas: uma linha por (linha_id, filing) com `conceito` (ou None). Devolve
    {linha_id: (conceito, confianca, n_filings, propaga)} quando o conceito majoritário passa de MAJORITARIO
    dos filings classificados. `propaga` (o conceito vale também para os filings em que a regra não pegou)
    só vale se ao menos metade dos filings da linha foi classificada: uma linha em que 1 de 10 nomes casou
    quase sempre é uma ligação errada da Etapa 6 ou outra conta com o nome parecido."""
    out = {}
    for lid, g in linhas.groupby("linha_id"):
        votos = Counter(c for c in g["conceito"] if c)
        if not votos:
            continue
        conceito, n = votos.most_common(1)[0]
        share = n / sum(votos.values())
        if share >= MAJORITARIO:
            out[lid] = (conceito, round(share, 3), len(g), sum(votos.values()) / len(g) >= 0.5)
    return out


def fatos_da_empresa(df: pd.DataFrame, linha_id: dict, cnpj: str):
    """df = latest_rows da empresa (plano padrão). linha_id[(fonte, data, cd)] = linha_id da DFC.
    Devolve (linha_conceito rows, fato rows)."""
    df = df[(df["ordem_exercicio"] == "Último") & (df["plano_contas"].fillna("padrao") == "padrao")].copy()
    if df.empty:
        return [], []
    df["dsn"] = df["ds_conta"].map(normalize_text)
    dfc = df[df["tipo_doc"] == "DFC_MI"].copy()

    # 1–2: rótulo por regra nas folhas N, votado por linha econômica
    rot = []
    for (fonte, data), g in dfc.groupby(["fonte", "data_referencia"]):
        folhas = _folhas(g["cd_conta"].unique())
        for r in g[g["st_conta_fixa"] == "N"].itertuples():
            if r.cd_conta in folhas:
                rot.append((fonte, data, r.cd_conta, linha_id.get((fonte, data, r.cd_conta)),
                            classificar(r.cd_conta, r.dsn, r.vl_conta if pd.notna(r.vl_conta) else None)))
    rot = pd.DataFrame(rot, columns=["fonte", "data", "cd", "linha_id", "conceito"])
    # linha sem linha_id (não deveria ocorrer) vota sozinha
    rot["linha_id"] = rot["linha_id"].fillna(rot["fonte"] + "|" + rot["data"] + "|" + rot["cd"])
    votos = votar(rot) if not rot.empty else {}
    def _final(r):
        v = votos.get(r.linha_id)
        if v is None:
            return None
        return v[0] if (v[3] or r.conceito == v[0]) else None
    rot["conceito_final"] = [_final(r) for r in rot.itertuples()]
    rot["confianca"] = rot["linha_id"].map(lambda l: votos.get(l, (None, 0.0))[1])
    lc = [(cnpj, "DFC_MI", lid, c, "regra", conf, n) for lid, (c, conf, n, _p) in votos.items()]

    # 3: fatos por filing
    fatos = []
    dva = df[(df["tipo_doc"] == "DVA") & (df["cd_conta"] == "7.04.01")]
    da_dva = {(r.fonte, r.data_referencia): abs(r.vl_conta) for r in dva.itertuples() if pd.notna(r.vl_conta)}
    sinal = {k: v[3] for k, v in CONCEITOS.items()}
    for (fonte, data), g in dfc.groupby(["fonte", "data_referencia"]):
        ini, fim = _periodo(g)
        sel = rot[(rot["fonte"] == fonte) & (rot["data"] == data) & rot["conceito_final"].notna()]
        vl = g.set_index("cd_conta")["vl_conta"]
        por_c = defaultdict(lambda: [0.0, 0, []])
        for r in sel.itertuples():
            v = vl.get(r.cd)
            if isinstance(v, pd.Series):
                v = v.iloc[0]
            if pd.isna(v):
                continue
            esp = sinal[r.conceito_final]
            if esp and v and (v > 0) != (esp > 0):
                continue   # o voto da linha econômica não vale contra o sinal desta célula (ex.: venda de tesouraria)
            por_c[r.conceito_final][0] += float(v)
            por_c[r.conceito_final][1] += 1
            por_c[r.conceito_final][2].append(r.confianca)
        base = {c: (s, n, min(cf)) for c, (s, n, cf) in por_c.items()}
        # derivados
        for tot, partes in (("da_total", ("da_ex_ppa", "da_direito_uso", "da_ppa")),
                            ("capex_total", ("capex_imob", "capex_intang", "capex_conjunto"))):
            ps = [base[p] for p in partes if p in base]
            if ps:
                base[tot] = (sum(p[0] for p in ps), sum(p[1] for p in ps), min(p[2] for p in ps))
        saidas_602 = g[(g["cd_conta"].str.startswith("6.02.")) & (g["vl_conta"] < 0)]["vl_conta"].sum()
        for c, (s, n, conf) in base.items():
            chk = "ok"
            esp = sinal[c]
            if esp and s != 0 and (s > 0) != (esp > 0):
                chk = "sinal_trocado"
            elif c == "da_total":
                gab = da_dva.get((fonte, data))
                if not gab:
                    chk = "sem_gabarito"
                elif abs(s - gab) <= TOL_DA * gab:
                    chk = "ok"
                else:
                    # a DVA 7.04.01 muda de definição por empresa (com ou sem direito de uso e mais-valia):
                    # se alguma das combinações fecha com a DVA, o fato vale e a checagem registra qual
                    a, u, m = (base[k][0] if k in base else 0.0 for k in ("da_ex_ppa", "da_direito_uso", "da_ppa"))
                    alt = [n for n, v in (("sem_ppa", a + u), ("sem_uso", a + m), ("so_ex_ppa", a)) if abs(v - gab) <= TOL_DA * gab]
                    chk = f"ok_{alt[0]}" if alt else "divergente"
            elif c == "capex_total" and saidas_602 and abs(s) > abs(saidas_602) * 1.001 + 1000:
                chk = "maior_que_pai"
            metodo = "derivado" if CONCEITOS[c][4] else "regra"
            fatos.append((cnpj, fonte, data, ini, fim, c, s, n, metodo, round(conf, 3), chk,
                          1 if chk.startswith("ok") or chk == "sem_gabarito" else 0))

    # contas S do plano padrão
    for conc, (tipo, cd) in CONTAS_S.items():
        s = df[(df["tipo_doc"] == tipo) & (df["cd_conta"] == cd) & (df["st_conta_fixa"] == "S")]
        for (fonte, data), g in s.groupby(["fonte", "data_referencia"]):
            ini = g["periodo_ini"].min() if (g["periodo_ini"] != "NA").any() else "NA"
            # fluxo no ITR: o acumulado (início mais antigo); balanço: a data
            gg = g[g["periodo_ini"] == ini]
            v = gg["vl_conta"].iloc[0]
            if pd.isna(v):
                continue
            fatos.append((cnpj, fonte, data, ini, gg["periodo_fim"].iloc[0], conc, float(v), 1, "S", 1.0, "ok", 1))
    return lc, fatos


CONTAS_DMPL = {"dividendos_declarados": ("5.04.06", "5.04.07"), "aumento_capital": ("5.04.01",),
               "recompra_dmpl": ("5.04.04",)}
# a empresa abre parte dos dividendos em contas próprias sob 5.04 ("Aprovação da Proposta de Dividendo", "Dividendos a
# não controladores", "Dividendo adicional"): entram as negativas com dividendo/JCP no nome, fora prescrito e reversão
_DIV_N = re.compile(r"dividend|juros sobre (o )?capital|\bjcp\b|\bjscp\b")
_DIV_N_FORA = re.compile(r"prescri|revers|receb|a receber")


def fatos_dmpl(conn, cnpj: str) -> list[tuple]:
    """Fatos das contas fixas da DMPL (coluna PL consolidado, coluna 'Último', versão vigente de cada filing). Banco sem
    a tabela dmpl = nenhum fato. No ITR, como a DFC, o período é o acumulado do ano."""
    try:
        rows = conn.execute(
            """SELECT d.fonte, d.data_referencia, d.dt_ini_exerc, d.dt_fim_exerc, d.cd_conta, d.vl_conta, d.ds_conta,
                      d.st_conta_fixa
               FROM dmpl d JOIN (SELECT fonte, data_referencia, MAX(versao) AS v FROM dmpl
                                 WHERE cnpj_companhia = ? GROUP BY 1, 2) u
                 ON u.fonte = d.fonte AND u.data_referencia = d.data_referencia AND u.v = d.versao
               WHERE d.cnpj_companhia = ? AND d.coluna = 'pl_consolidado' AND d.ordem_exercicio = 'Último'
                 AND (d.cd_conta IN ('5.04.01', '5.04.04', '5.04.06', '5.04.07')
                      OR (d.cd_conta LIKE '5.04.%' AND d.st_conta_fixa = 'N'))""", (cnpj, cnpj)).fetchall()
    except Exception:   # sqlite3.OperationalError: banco anterior à tabela dmpl
        return []
    por = defaultdict(dict)
    for fonte, data, ini, fim, cd, vl, ds, st in rows:
        if st == "N":
            dsn = normalize_text(ds or "")
            if not (vl and vl < 0 and _DIV_N.search(dsn) and not _DIV_N_FORA.search(dsn)):
                continue
            cd = "N:" + cd
        por[(fonte, data, ini, fim)][cd] = vl
    out = []
    for (fonte, data, ini, fim), v in por.items():
        for conc, cds in CONTAS_DMPL.items():
            if conc == "dividendos_declarados":
                cds = cds + tuple(c for c in v if c.startswith("N:"))
            vals = [v[c] for c in cds if v.get(c) is not None]
            if vals:
                out.append((cnpj, fonte, data, ini, fim, conc, float(sum(vals)), len(vals), "S", 1.0, "ok", 1))
    return out


def construir(conn, cnpj: str) -> tuple[int, int]:
    df = latest_rows(conn, cnpj=cnpj)
    ids = {(r[0], r[1], r[2]): r[3] for r in conn.execute(
        "SELECT fonte, data_referencia, cd_conta, linha_id FROM linha_empresa "
        "WHERE cnpj_companhia = ? AND tipo_doc = 'DFC_MI'", (cnpj,))}
    lc, fatos = fatos_da_empresa(df, ids, cnpj)
    fatos += fatos_dmpl(conn, cnpj)
    conn.execute("DELETE FROM linha_conceito WHERE cnpj_companhia = ?", (cnpj,))
    conn.execute("DELETE FROM fato_padronizado WHERE cnpj_companhia = ?", (cnpj,))
    conn.executemany("INSERT INTO linha_conceito VALUES (?,?,?,?,?,?,?)", lc)
    conn.executemany("INSERT OR REPLACE INTO fato_padronizado VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", fatos)
    conn.commit()
    return len(lc), len(fatos)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cnpj")
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args(argv)
    if not a.cnpj and not a.full:
        ap.error("informe --cnpj ou --full")
    conn = get_db()
    conn.executescript(DDL)
    conn.execute("DELETE FROM conceito")
    conn.executemany("INSERT INTO conceito VALUES (?,?,?,?,?,?)",
                     [(k, v[0], v[1], v[2], v[3], int(v[4])) for k, v in CONCEITOS.items()])
    conn.commit()
    cnpjs = [a.cnpj] if a.cnpj else [r[0] for r in conn.execute("SELECT cnpj FROM companies ORDER BY cnpj")]
    t_l = t_f = 0
    for i, c in enumerate(cnpjs, 1):
        nl, nf = construir(conn, c)
        t_l += nl
        t_f += nf
        print(f"  [{i}/{len(cnpjs)}] {c}: {nl} linhas rotuladas, {nf} fatos")
    print(f"linha_conceito={t_l} fato_padronizado={t_f}")


if __name__ == "__main__":
    main()
