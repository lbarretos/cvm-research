"""Etapa 6: gera o conjunto de avaliação v0 (perguntas com resposta conhecida) a partir do banco.

Cada pergunta traz a resposta, a consulta que a produz e a armadilha que ela testa. A resposta
é o que o banco diz na data da geração: regenerar depois de uma recarga pode mudar números
reapresentados (ver CLAUDE.md, "A CVM não arquiva versões anteriores").

    python st6_golden.py /caminho/cvm_research.db docs/proximos-passos/avaliacao/golden_v0.json
"""
import json
import random
import sqlite3
import sys
from datetime import date

random.seed(7)
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
out = []

def add(tipo, pergunta, resposta, sql, armadilha, tol=0.005):
    assert resposta not in (None, [], ""), pergunta
    out.append({"id": f"q{len(out)+1:03d}", "tipo": tipo, "pergunta": pergunta, "resposta": resposta,
                "tolerancia_rel": tol if isinstance(resposta, (int, float)) else None,
                "sql_referencia": " ".join(sql.split()), "armadilha": armadilha})

emp = {r["cnpj"]: r for r in c.execute("SELECT cnpj, ticker, nome_cvm FROM companies")}
padrao = [r[0] for r in c.execute("""SELECT cnpj_companhia FROM vw_plano_contas WHERE fonte='DFP' AND data_referencia='2024-12-31'
                                     AND plano_contas='padrao' ORDER BY cnpj_companhia""")]
amostra = random.sample(padrao, 8)

for cn in amostra[:4]:
    tk = emp[cn]["ticker"]
    sql = f"SELECT receita_liquida, lucro_liquido FROM vw_dre WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='2024-12-31'"
    r = c.execute(sql).fetchone()
    add("numero", f"Qual a receita líquida consolidada de {tk} em 2024 (DFP), em R$?", r[0], sql,
        "resolver o CNPJ pelo ticker; usar DFP (anual), não somar ITRs")
    add("numero", f"Qual o lucro líquido consolidado de {tk} em 2024 (DFP), em R$?", r[1], sql,
        "3.11 é o lucro consolidado (inclui não controladores)")

for cn in amostra[4:6]:
    tk = emp[cn]["ticker"]
    sql = f"""SELECT vl_final FROM demonstrativos_trimestrais WHERE cnpj_companhia='{cn}' AND tipo_doc='DRE' AND safra='original'
              AND cd_conta='3.01' AND dt_fim_exerc='2024-12-31' AND trimestre=4"""
    r = c.execute(sql).fetchone()
    if r and r[0] is not None:
        add("numero", f"Qual a receita líquida de {tk} no 4T24 (trimestre isolado, como divulgado na época)?", r[0], sql,
            "o 4T não existe no ITR: é DFP − acumulado do 3T; usar safra original")

for cn in amostra[6:8]:
    tk = emp[cn]["ticker"]
    sql = f"""SELECT vl_conta FROM demonstrativos_contabeis WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND tipo_doc='DVA'
              AND data_referencia='2024-12-31' AND ordem_exercicio='Último' AND cd_conta='7.04.01'"""
    r = c.execute(sql).fetchone()
    if r:
        add("numero", f"Quanto {tk} registrou de depreciação, amortização e exaustão em 2024?", abs(r[0]), sql,
            "D&A está na DVA 7.04.01 (conta fixa); na DFC fica em linhas criadas pela empresa")

bancos = [r[0] for r in c.execute("SELECT DISTINCT cnpj_companhia FROM vw_plano_contas WHERE plano_contas='banco'")]
for cn in bancos[:2]:
    tk = emp[cn]["ticker"]
    sql = f"SELECT lucro_liquido FROM vw_dre_financeiro WHERE cnpj_companhia='{cn}' AND fonte='DFP' AND data_referencia='2024-12-31'"
    r = c.execute(sql).fetchone()
    add("numero", f"Qual o lucro líquido de {tk} em 2024 (DFP)?", r[0], sql,
        "banco: vw_dre volta NULL; 3.11 do plano padrão não é o lucro de banco")

for cn in random.sample(padrao, 4):
    tk = emp[cn]["ticker"]
    sql = f"""SELECT COUNT(*) FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Fato Relevante'
              AND data_entrega BETWEEN '2025-01-01' AND '2025-12-31'"""
    n = c.execute(sql).fetchone()[0]
    add("contagem", f"Quantos fatos relevantes {tk} divulgou em 2025?", n, sql,
        "filtrar por data_entrega, não data_referencia; contar reapresentações é discutível — resposta inclui todas", tol=0)
    sql = f"""SELECT data_entrega, assunto FROM ipe_docs WHERE cnpj_companhia='{cn}' AND categoria='Fato Relevante'
              AND data_entrega < '2026-09-01' ORDER BY data_entrega DESC LIMIT 1"""
    r = c.execute(sql).fetchone()
    if r:
        add("documento", f"Qual foi o último fato relevante de {tk} antes de setembro de 2026, e sobre o quê?",
            {"data_entrega": r[0][:10], "assunto": r[1]}, sql, "ordenar por data_entrega; ler o texto para dizer o tema")

for cn in random.sample(padrao, 3):
    tk = emp[cn]["ticker"]
    sql = f"""SELECT acionista, percentual_total_acoes_circulacao FROM vw_acionistas_diretos WHERE cnpj_companhia='{cn}'
              AND acionista NOT LIKE 'Outros%' AND acionista NOT LIKE '%Tesouraria%'
              ORDER BY percentual_total_acoes_circulacao DESC LIMIT 1"""
    r = c.execute(sql).fetchone()
    if r:
        add("fato", f"Quem é o maior acionista direto de {tk} e com quantos % do capital total?",
            {"acionista": r[0], "pct_total": r[1]}, sql,
            "fre_posicao_acionaria mistura níveis da cadeia de controle; usar a view de diretos")

sql = """SELECT c.ticker, cf.periodo_fim FROM consistency_flags cf JOIN companies c ON c.cnpj=cf.cnpj_companhia
         WHERE cf.layer=2 AND cf.classificacao='reapresentacao' AND cf.tipo_doc='DRE' AND cf.cd_conta='3.11'
         AND cf.fonte_cmp='DFP' AND cf.periodo_fim LIKE '%-12-31' AND ABS(cf.diff_rel) > 0.05 ORDER BY cf.periodo_fim DESC LIMIT 2"""
for tk, pf in c.execute(sql).fetchall():
    s2 = f"""SELECT valor_ref, valor_cmp FROM consistency_flags cf JOIN companies c ON c.cnpj=cf.cnpj_companhia
             WHERE c.ticker='{tk}' AND layer=2 AND tipo_doc='DRE' AND cd_conta='3.11' AND periodo_fim='{pf}' AND fonte_cmp='DFP'"""
    r = c.execute(s2).fetchone()
    add("numero_par", f"O lucro líquido de {tk} em {pf[:4]} foi reapresentado? Dê o original e o reapresentado.",
        {"original": r[0], "reapresentado": r[1]}, s2, "mostrar os dois lado a lado; o padrão da base é o original")

add("sem_dado", "Qual foi o fato relevante mais recente da PETR4 publicado ontem?",
    "resposta correta: informar a data do último dado na base (MAX(data_entrega)) e apontar o RAD", 
    "SELECT MAX(data_entrega) FROM ipe_docs", "defasagem semanal do IPE: ausência de dado não é ausência de evento")

json.dump({"gerado_em": date.today().isoformat(), "banco": sys.argv[1], "n": len(out), "perguntas": out},
          open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print(f"{len(out)} perguntas → {sys.argv[2]}")
from collections import Counter
print(Counter(q["tipo"] for q in out))
