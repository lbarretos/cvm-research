"""Etapa 2: conjunto de avaliação v1 (~80 perguntas). Mantém as 28 do v0 (mesmos ids) e acrescenta o que o v0 não
cobria: DFC por conceito (get_financials), séries, ITR isolado × acumulado, 4T da DFC, seguradora, exercício fora do
calendário, insiders, recompra, FRE, assembleias, documentos e adversariais.

A resposta é o que o banco diz na data da geração. As perguntas de DFC usam empresas em que o conceito está numa
única linha com nome inequívoco, para a resposta não depender das regras da Etapa 7 (a verdade é a linha, lida direto).

    .venv/bin/python docs/proximos-passos/stress/st2_golden_v1.py "$PWD/cvm_research.db" docs/proximos-passos/avaliacao/golden_v1.json
"""
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, "scripts/analysis")
from consistency_utils import normalize_text  # noqa: E402

random.seed(11)
RAIZ = os.path.dirname(os.path.abspath(sys.argv[2]))
V0 = json.load(open(os.path.join(RAIZ, "golden_v0.json")))["perguntas"]
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
out = [dict(q) for q in V0]


def add(tipo, pergunta, resposta, sql, armadilha, tol=0.005, familia=""):
    assert resposta not in (None, [], "", {}), pergunta
    out.append({"id": f"q{len(out) + 1:03d}", "tipo": tipo, "familia": familia, "pergunta": pergunta,
                "resposta": resposta,
                "tolerancia_rel": (0 if tipo in ("contagem", "quantidade") else tol)
                if isinstance(resposta, (int, float)) or tipo == "serie" else None,
                "sql_referencia": " ".join(sql.split()), "armadilha": armadilha})


emp = {r["cnpj"]: r for r in c.execute("SELECT cnpj, ticker, nome_cvm FROM companies")}
padrao = [r[0] for r in c.execute("""SELECT DISTINCT cnpj_companhia FROM filings WHERE fonte='DFP' AND tipo_doc='DFC_MI'
                                     AND data_referencia='2024-12-31' AND plano_contas='padrao' ORDER BY 1""")]
random.shuffle(padrao)
em_uso = set()


def dfc_linhas(cn, ano, prefixo):
    """Linhas N folha da DFC (Último, versão vigente) de um DFP sob um prefixo, com nome normalizado."""
    rows = c.execute("""SELECT d.cd_conta, d.ds_conta, d.vl_conta FROM demonstrativos_contabeis d
        JOIN filings f ON f.cnpj_companhia=d.cnpj_companhia AND f.fonte=d.fonte AND f.tipo_doc=d.tipo_doc
         AND f.data_referencia=d.data_referencia AND f.versao=d.versao
        WHERE d.cnpj_companhia=? AND d.fonte='DFP' AND d.tipo_doc='DFC_MI' AND d.data_referencia=?
          AND d.ordem_exercicio='Último' AND d.st_conta_fixa='N' AND d.cd_conta LIKE ?""",
                     (cn, f"{ano}-12-31", prefixo + ".%")).fetchall()
    cds = {r[0] for r in rows}
    return [(r[0], normalize_text(r[1]), r[2]) for r in rows if not any(o.startswith(r[0] + ".") for o in cds)]


def linha_unica(cn, ano, prefixo, nomes):
    achados = [x for x in dfc_linhas(cn, ano, prefixo) if x[1] in nomes and x[2] is not None]
    return achados[0] if len(achados) == 1 else None


def tk(cn):
    return emp[cn]["ticker"]


def escolher(n, teste, usados=None):
    achados = []
    for cn in padrao:
        if len(achados) == n:
            break
        if cn in (usados or set()):
            continue
        r = teste(cn)
        if r:
            achados.append((cn, r))
    return achados


DIV = {"dividendos pagos", "pagamento de dividendos", "dividendos e juros sobre capital proprio pagos",
       "juros sobre capital proprio pagos", "pagamento de dividendos e juros sobre capital proprio"}
CAPEX_I = {"aquisicao de imobilizado", "aquisicoes de imobilizado", "adicoes ao imobilizado", "aquisicao de ativo imobilizado"}
CAPEX_N = {"aquisicao de intangivel", "aquisicoes de intangivel", "adicoes ao intangivel", "aquisicao de ativo intangivel"}
JUROS = {"juros pagos", "pagamento de juros", "pagamento de juros sobre emprestimos e financiamentos"}
RECOMPRA = {"recompra de acoes", "aquisicao de acoes em tesouraria", "acoes em tesouraria", "compra de acoes em tesouraria"}


def sql_linha(cn, ano, cd):
    return (f"SELECT vl_conta FROM demonstrativos_contabeis WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND tipo_doc='DFC_MI' "
            f"AND data_referencia='{ano}-12-31' AND ordem_exercicio='Último' AND cd_conta='{cd}'")


# ── A. DFC por conceito (domínio do get_financials) ──────────────────────────
for cn, (cd, nm, v) in escolher(3, lambda x: linha_unica(x, 2024, "6.03", DIV)):
    add("numero", f"Quanto {tk(cn)} pagou de dividendos e JCP em 2024, segundo a DFC? (valor positivo, em R$)", abs(v),
        sql_linha(cn, 2024, cd), "dividendos pagos estão numa linha N da DFC cujo código varia por empresa; não confundir com declarados",
        familia="dfc_conceito")
for cn, (a, b) in escolher(3, lambda x: (linha_unica(x, 2024, "6.02", CAPEX_I), linha_unica(x, 2024, "6.02", CAPEX_N))
                          if linha_unica(x, 2024, "6.02", CAPEX_I) and linha_unica(x, 2024, "6.02", CAPEX_N) else None):
    add("numero", f"Qual o capex de {tk(cn)} em 2024 (aquisição de imobilizado mais intangível, na DFC), em R$ positivos?",
        abs(a[2]) + abs(b[2]), sql_linha(cn, 2024, a[0]) + " + " + sql_linha(cn, 2024, b[0]),
        "capex = soma de duas linhas N; somar só uma erra", familia="dfc_conceito")
for cn, (cd, nm, v) in escolher(2, lambda x: linha_unica(x, 2024, "6.0", JUROS)):
    add("numero", f"Quanto {tk(cn)} pagou de juros em 2024 (caixa, DFC), em R$ positivos?", abs(v), sql_linha(cn, 2024, cd),
        "juros pagos em caixa, não os provisionados somados de volta em 6.01.01", familia="dfc_conceito")
for cn, (cd, nm, v) in escolher(2, lambda x: linha_unica(x, 2024, "6.03", RECOMPRA)):
    add("numero", f"Quanto {tk(cn)} gastou com recompra de ações em 2024 segundo a DFC, em R$ positivos?", abs(v),
        sql_linha(cn, 2024, cd), "linha N de financiamento; vem com sinal negativo", familia="dfc_conceito")
# séries: o código da linha muda entre anos
def serie_div(x):
    a, b = linha_unica(x, 2023, "6.03", DIV), linha_unica(x, 2024, "6.03", DIV)
    return (a, b) if a and b and a[0] != b[0] else None
for cn, (a, b) in escolher(2, serie_div):
    add("serie", f"Quanto {tk(cn)} pagou de dividendos e JCP em 2023 e em 2024 (DFC, valores positivos em R$)?",
        {"2023": abs(a[2]), "2024": abs(b[2])}, sql_linha(cn, 2023, a[0]) + " ; " + sql_linha(cn, 2024, b[0]),
        f"o código da linha mudou entre os anos ({a[0]} → {b[0]}): juntar por código mistura contas", familia="dfc_serie")
for cn, _ in escolher(2, lambda x: True):
    for nome, cd in (("das atividades operacionais", "6.01"), ("das atividades de financiamento", "6.03")):
        r = c.execute(sql_linha(cn, 2024, cd).replace("vl_conta FROM", "vl_conta FROM")).fetchone()
        if r and r[0] is not None:
            add("numero", f"Qual o caixa líquido {nome} de {tk(cn)} em 2024 (DFC)? Mantenha o sinal, em R$.", r[0],
                sql_linha(cn, 2024, cd), "conta fixa 6.0x da DFC; manter o sinal", familia="dfc_fixa")

# ── B. Balanço, DRE, ITR e 4T ────────────────────────────────────────────────
amostra = random.sample(padrao, 14)
for cn in amostra[:2]:
    sql = f"SELECT ativo_total, patrimonio_liquido, caixa, divida_curto_prazo + COALESCE(divida_longo_prazo,0) FROM vw_balanco WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='2024-12-31'"
    r = c.execute(sql).fetchone()
    add("numero", f"Qual o ativo total de {tk(cn)} em 31/12/2024, em R$?", r[0], sql, "vw_balanco; BPA+BPP", familia="balanco")
    add("numero", f"Qual a dívida bruta (curto + longo prazo, financeira) de {tk(cn)} em 31/12/2024, em R$?", r[3], sql,
        "divida_curto_prazo + divida_longo_prazo da vw_balanco (contas 2.01.04 e 2.02.01)", familia="balanco")
for cn in amostra[2:4]:
    sql = f"SELECT ebit, receita_liquida FROM vw_dre WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='2024-12-31'"
    r = c.execute(sql).fetchone()
    if r and r[1]:
        add("percentual", f"Qual a margem EBIT de {tk(cn)} em 2024 (EBIT sobre receita líquida), em %?", 100 * r[0] / r[1], sql,
            "ebit/receita_liquida da vw_dre (DFP)", tol=0.02, familia="dre_derivada")
for cn in amostra[4:8]:
    sql_iso = f"SELECT receita_liquida FROM vw_dre WHERE cnpj_companhia='{cn}' AND fonte='ITR' AND data_referencia='2025-06-30'"
    sql_ac = f"SELECT receita_liquida FROM vw_dre_acumulada WHERE cnpj_companhia='{cn}' AND fonte='ITR' AND data_referencia='2025-06-30'"
    a, b = c.execute(sql_iso).fetchone(), c.execute(sql_ac).fetchone()
    if a and b and a[0] and b[0]:
        add("numero", f"Qual a receita líquida de {tk(cn)} no 2T25 isolado (abril a junho de 2025), em R$?", a[0], sql_iso,
            "ITR 2T tem duas linhas por conta: isolado e acumulado; usar o trimestre isolado", familia="itr")
        add("numero", f"Qual a receita líquida acumulada de {tk(cn)} no primeiro semestre de 2025, em R$?", b[0], sql_ac,
            "acumulado do ano (vw_dre_acumulada), não o trimestre", familia="itr")
for cn in amostra[8:10]:
    sql = f"""SELECT vl_final FROM demonstrativos_trimestrais WHERE cnpj_companhia='{cn}' AND tipo_doc='DFC_MI' AND safra='original'
              AND cd_conta='6.01' AND dt_fim_exerc='2024-12-31' AND trimestre=4"""
    r = c.execute(sql).fetchone()
    if r and r[0] is not None:
        add("numero", f"Qual foi o caixa operacional (DFC) de {tk(cn)} no 4T24 isolado, em R$?", r[0], sql,
            "a DFC só vem acumulada: o 4T é DFP − acumulado do 3T (demonstrativos_trimestrais, safra original)", familia="trimestral")

# ── C. Bancos, seguradoras e exercício fora do calendário ────────────────────
for cn in [r[0] for r in c.execute("SELECT DISTINCT cnpj_companhia FROM vw_plano_contas WHERE plano_contas='seguradora'")][:2]:
    sql = f"SELECT lucro_liquido FROM vw_dre_seguradora WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='2024-12-31'"
    r = c.execute(sql).fetchone()
    if r and r[0] is not None:
        add("numero", f"Qual o lucro líquido de {tk(cn)} em 2024 (DFP)?", r[0], sql,
            "seguradora: vw_dre volta NULL; usar vw_dre_seguradora (3.13)", familia="plano")
for cn in [r[0] for r in c.execute("SELECT DISTINCT cnpj_companhia FROM vw_plano_contas WHERE plano_contas='banco'")][2:4]:
    sql = f"SELECT ativo_total FROM vw_balanco WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='2024-12-31'"
    r = c.execute(sql).fetchone()
    if r and r[0]:
        add("numero", f"Qual o ativo total de {tk(cn)} em 31/12/2024?", r[0], sql, "ativo_total vale em todos os planos", familia="plano")
fora = c.execute("""SELECT DISTINCT c.ticker, f.cnpj_companhia, f.data_referencia FROM filings f JOIN companies c ON c.cnpj=f.cnpj_companhia
                    WHERE f.fonte='DFP' AND f.tipo_doc='DRE' AND f.plano_contas='padrao' AND f.data_referencia LIKE '2024-%'
                      AND f.data_referencia NOT LIKE '%-12-31' ORDER BY 1 LIMIT 3""").fetchall()
for t, cn, dr in fora[:2]:
    sql = f"SELECT receita_liquida FROM vw_dre WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='{dr}'"
    r = c.execute(sql).fetchone()
    if r and r[0]:
        add("numero", f"Qual a receita líquida de {t} no exercício social encerrado em {dr[8:]}/{dr[5:7]}/{dr[:4]} (DFP)?",
            r[0], sql, "exercício fora do ano-calendário: a data de referência não é 31/12", familia="calendario")

# ── D. Insiders, recompra, FRE, assembleias ──────────────────────────────────
COMPRAS = "('Compra à vista','Compra à termo','Compra')"
for cn in random.sample(padrao, 20):
    sql = f"""SELECT COUNT(*), ROUND(SUM(v.volume), 2) FROM vlmo_movimentacoes v WHERE v.cnpj_companhia='{cn}'
              AND v.versao = (SELECT MAX(versao) FROM vlmo_movimentacoes m WHERE m.cnpj_companhia=v.cnpj_companhia AND m.data_referencia=v.data_referencia)
              AND v.tipo_movimentacao IN {COMPRAS} AND v.data_movimentacao BETWEEN '2025-01-01' AND '2025-12-31'"""
    n, vol = c.execute(sql).fetchone()
    if n and n >= 3 and vol:
        add("contagem", f"Quantas operações de compra em mercado (à vista, a termo ou compra simples) os insiders de {tk(cn)} fizeram em 2025?",
            n, sql, "só a última versão de cada formulário mensal; excluir Saldo Inicial/Final, posse, aluguel", familia="insider")
        add("numero", f"Qual o volume financeiro total, em R$, das compras de insiders de {tk(cn)} em 2025?", vol, sql,
            "somar volume só das compras da última versão de cada mês", tol=0.01, familia="insider")
        break
for cn in random.sample(padrao, 40):
    sql = f"SELECT COUNT(*) FROM recompra_programas WHERE cnpj_companhia='{cn}' AND situacao='Em Andamento'"
    n = c.execute(sql).fetchone()[0]
    if n >= 1:
        add("contagem", f"Quantos programas de recompra de ações de {tk(cn)} estão em andamento?", n, sql,
            "recompra_programas.situacao = 'Em Andamento'", familia="recompra")
        s2 = f"SELECT data_deliberacao, data_final_prazo FROM recompra_programas WHERE cnpj_companhia='{cn}' ORDER BY data_deliberacao DESC LIMIT 1"
        r = c.execute(s2).fetchone()
        if r and r[1]:
            add("fato", f"Quando {tk(cn)} deliberou seu programa de recompra mais recente e até quando vai o prazo?",
                {"data_deliberacao": r[0][:10], "data_final_prazo": r[1][:10]}, s2, "ordenar por data_deliberacao", familia="recompra")
        break
for cn in random.sample(padrao, 40):
    sql = f"""SELECT quantidade_total_acoes FROM fre_capital_social WHERE cnpj_companhia='{cn}' AND tipo_capital='Capital Integralizado'
              AND data_referencia=(SELECT MAX(data_referencia) FROM fre_capital_social WHERE cnpj_companhia='{cn}' AND tipo_capital='Capital Integralizado')
              AND versao=(SELECT MAX(versao) FROM fre_capital_social WHERE cnpj_companhia='{cn}' AND tipo_capital='Capital Integralizado'
                          AND data_referencia=(SELECT MAX(data_referencia) FROM fre_capital_social WHERE cnpj_companhia='{cn}' AND tipo_capital='Capital Integralizado'))"""
    r = c.execute(sql).fetchone()
    if r and r[0]:
        add("quantidade", f"Quantas ações compõem o capital integralizado de {tk(cn)} segundo o FRE mais recente?", r[0], sql,
            "fre_capital_social: tipo_capital 'Capital Integralizado', FRE e versão mais recentes", familia="fre")
        break
for cn in random.sample(padrao, 40):
    sql = f"""SELECT numero_membros FROM fre_remuneracao_orgao WHERE cnpj_companhia='{cn}' AND orgao_administracao='Conselho de Administração'
              AND data_referencia=(SELECT MAX(data_referencia) FROM fre_remuneracao_orgao WHERE cnpj_companhia='{cn}')
              ORDER BY versao DESC LIMIT 1"""
    r = c.execute(sql).fetchone()
    if r and r[0]:
        add("quantidade", f"Quantos membros tem o Conselho de Administração de {tk(cn)} segundo a remuneração do FRE mais recente?",
            int(r[0]), sql, "fre_remuneracao_orgao: órgão 'Conselho de Administração', FRE mais recente", familia="fre")
        break
for cn in random.sample(padrao, 30)[:2]:
    sql = f"""SELECT COUNT(*) FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Assembleia' AND tipo IN ('AGO','AGE','AGO/E')
              AND especie='Edital de Convocação' AND data_entrega BETWEEN '2025-01-01' AND '2025-12-31'"""
    n = c.execute(sql).fetchone()[0]
    add("contagem", f"Quantos editais de convocação de assembleia (AGO, AGE ou AGO/E) {tk(cn)} entregou em 2025?", n, sql,
        "categoria Assembleia, especie Edital de Convocação, filtrar por data_entrega", familia="assembleia")
for cn in random.sample(padrao, 10):
    sql = f"""SELECT data_entrega, tipo FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Assembleia' AND especie='Ata'
              AND tipo IN ('AGO','AGO/E') ORDER BY data_entrega DESC LIMIT 1"""
    r = c.execute(sql).fetchone()
    if r:
        add("fato", f"Quando {tk(cn)} entregou a ata da última assembleia geral ordinária (AGO ou AGO/E)?",
            {"data_entrega": r[0][:10], "tipo": r[1]}, sql, "especie 'Ata', tipo AGO ou AGO/E; data_entrega", familia="assembleia")
        break

# ── E. Documentos ────────────────────────────────────────────────────────────
for cn in random.sample(padrao, 40):
    sql = f"""SELECT data_entrega, assunto FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Comunicado ao Mercado'
              AND data_entrega < '2026-09-01' ORDER BY data_entrega DESC LIMIT 1"""
    r = c.execute(sql).fetchone()
    if r:
        add("documento", f"Qual foi o último comunicado ao mercado de {tk(cn)} antes de setembro de 2026, e sobre o quê?",
            {"data_entrega": r[0][:10], "assunto": r[1]}, sql, "categoria 'Comunicado ao Mercado', data_entrega", familia="documento")
        break
for cn in random.sample(padrao, 4)[:2]:
    sql = f"""SELECT COUNT(*) FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Aviso aos Acionistas'
              AND data_entrega BETWEEN '2025-01-01' AND '2025-12-31'"""
    add("contagem", f"Quantos avisos aos acionistas {tk(cn)} divulgou em 2025?", c.execute(sql).fetchone()[0], sql,
        "categoria 'Aviso aos Acionistas', data_entrega (inclui reapresentações)", familia="documento")
for cn in random.sample(padrao, 40):
    sql = f"""SELECT data_entrega FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Dados Econômico-Financeiros'
              AND tipo='Press-release' AND data_referencia='2026-06-30' ORDER BY data_entrega DESC LIMIT 1"""
    r = c.execute(sql).fetchone()
    if r:
        add("fato", f"Em que data {tk(cn)} entregou o release de resultados do 2T26?", {"data_entrega": r[0][:10]}, sql,
            "release de resultados = Dados Econômico-Financeiros / Press-release; não existe categoria 'Resultado'", familia="documento")
        break
for cn in random.sample(padrao, 80):
    sql = f"""SELECT COUNT(*) FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Fato Relevante'
              AND data_entrega BETWEEN '2025-01-01' AND '2025-12-31' AND (assunto LIKE '%ividend%' OR assunto LIKE '%rovento%' OR assunto LIKE '%JCP%'
              OR assunto LIKE '%apital próprio%' OR assunto LIKE '%apital proprio%')"""
    n = c.execute(sql).fetchone()[0]
    if n >= 1:
        add("contagem", f"Quantos fatos relevantes de {tk(cn)} em 2025 têm no assunto dividendos, JCP ou proventos?", n, sql,
            "busca por tema no assunto; aceita-se a contagem que usa assunto (reapresentações incluídas)", familia="documento")
        break

# ── F. Adversariais e sem dado ───────────────────────────────────────────────
fora_base = next(t for t in ("ELET6", "AMER3", "MMXM3", "OIBR3", "CIEL3", "BRML3", "LAME3")
                 if not c.execute("SELECT 1 FROM companies WHERE ticker=?", (t,)).fetchone())
add("sem_dado", f"Qual a receita líquida de {fora_base} em 2024?",
    f"resposta correta: dizer que {fora_base} não está na base (companies) e oferecer o onboarding ou apontar o RAD, sem inventar valor",
    f"SELECT COUNT(*) FROM companies WHERE ticker='{fora_base}'", "empresa fora da base: não inventar nem usar outra", familia="adversarial")
add("sem_dado", "Qual será a receita líquida da WEGE3 em 2027?",
    "resposta correta: dizer que a base só tem demonstrações publicadas (até a data do último ITR/DFP) e não projeções",
    "SELECT MAX(data_referencia) FROM filings WHERE fonte='ITR'", "pedido de projeção: sem dado", familia="adversarial")
add("sem_dado", "Qual o lucro líquido do Itaú em 2024?",
    "resposta correta: o 'Itaú' é ambíguo (Itaú Unibanco ITUB4 × Itaúsa ITSA4): resolver pela empresa mais provável (Itaú Unibanco) "
    "declarando a premissa ou perguntando; o valor de ITUB4 é o do banco (vw_dre_financeiro), nunca o NULL de vw_dre",
    "SELECT lucro_liquido FROM vw_dre_financeiro WHERE cnpj_companhia=(SELECT cnpj FROM companies WHERE ticker='ITUB4') AND fonte='DFP' AND data_referencia='2024-12-31'",
    "nome ambíguo + plano de banco", familia="adversarial")

json.dump({"gerado_em": date.today().isoformat(), "banco": os.path.relpath(sys.argv[1]), "n": len(out), "versao": "v1",
           "perguntas": out}, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print(f"{len(out)} perguntas → {sys.argv[2]}")
print(Counter(q["tipo"] for q in out))
print(Counter(q.get("familia", "v0") or "v0" for q in out))
