"""
Visualizador local (scripts/viewer/server.py): encadeamento das linhas entre colunas.

A tabela mostra uma linha por LINHA ECONÔMICA, não por cd_conta. Sem isso, a série
horizontal mistura contas diferentes sempre que a empresa renumera — o mesmo erro
que a Camada 6 corrigiu no banco, reproduzido na tela.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "viewer"))

import server  # noqa: E402


def col(**contas):
    """Coluna no formato {cd: (ds, st_conta_fixa)}; 'N' = conta criada pela empresa."""
    return {cd: (ds, "N") for cd, ds in contas.items()}


def series_de(colunas, ligacoes=None):
    """{cd na última coluna em que aparece: [cd por coluna]}"""
    s = server.encadear(colunas, ligacoes)
    return {x[max(x)]: [x.get(i) for i in range(len(colunas))] for x in s}


def test_renumeracao_vira_uma_linha_so():
    """Multiplan, DFC: no 1T o 6.03.08 é dividendos, no 2T é encargos de debêntures."""
    c1 = col(**{"6.03.06": "Pagamento de encargos e debêntures",
                "6.03.08": "Dividendos e juros sobre capital próprio"})
    c2 = col(**{"6.03.08": "Pagamento de encargos sobre debêntures",
                "6.03.09": "Dividendos e juros sobre o capital prórpio"})
    assert series_de([c1, c2]) == {"6.03.08": ["6.03.06", "6.03.08"],
                                   "6.03.09": ["6.03.08", "6.03.09"]}


def test_ligacao_gravada_pela_camada6_tem_precedencia():
    """Dentro de um exercício o vínculo vem pronto do banco (cd_conta_b), não é recalculado."""
    c1 = col(**{"6.03.01": "Alfa", "6.03.02": "Beta"})
    c2 = col(**{"6.03.09": "Alfa", "6.03.07": "Beta"})
    s = series_de([c1, c2], {1: {"6.03.09": "6.03.01", "6.03.07": "6.03.02"}})
    assert s == {"6.03.09": ["6.03.01", "6.03.09"], "6.03.07": ["6.03.02", "6.03.07"]}


def test_buraco_no_meio_nao_parte_a_linha_em_duas():
    """A empresa não abriu a conta num trimestre. Reata por código + nome idênticos."""
    c = col(**{"3.04.02.05": "Despesas de remuneração baseada em opção de ações"})
    s = server.encadear([c, col(**{"3.04.01": "Outra"}), c])
    assert len(s) == 2
    remu = [x for x in s if x.get(0) == "3.04.02.05"][0]
    assert remu == {0: "3.04.02.05", 2: "3.04.02.05"}


def test_par_ambiguo_nao_encadeia():
    """Mesmo critério do banco: na dúvida, duas linhas em vez de uma série inventada."""
    c1 = col(**{"6.03.09": "Captação de debêntures"})
    c2 = col(**{"6.03.12": "Emissão de debêntures"})          # score 0,744: ambíguo
    assert series_de([c1, c2]) == {"6.03.09": ["6.03.09", None], "6.03.12": [None, "6.03.12"]}


def test_linha_nova_e_linha_que_some():
    c1 = col(**{"6.03.01": "Alfa", "6.03.02": "Some aqui"})
    c2 = col(**{"6.03.01": "Alfa", "6.03.03": "Aparece agora"})
    s = series_de([c1, c2])
    assert s["6.03.01"] == ["6.03.01", "6.03.01"]
    assert s["6.03.02"] == ["6.03.02", None]
    assert s["6.03.03"] == [None, "6.03.03"]


def test_montar_rotula_pela_coluna_mais_recente_e_descarta_serie_vazia():
    c1 = col(**{"6.03.06": "Pagamento de encargos e debêntures", "6.03.07": "Só nulos"})
    c2 = col(**{"6.03.08": "Pagamento de encargos sobre debêntures"})
    colunas = [c1, c2]
    valores = [{"6.03.06": -144.9e6, "6.03.07": None}, {"6.03.08": -347.0e6}]
    linhas = server.montar(server.encadear(colunas), colunas, valores)
    assert [r["cd"] for r in linhas] == ["6.03.08"]                       # "Só nulos" sai
    r, = linhas
    assert r["ds"] == "Pagamento de encargos sobre debêntures"            # nome mais recente
    assert r["cds"] == ["6.03.06", "6.03.08"]                             # código por coluna
    assert r["v"] == [-144.9e6, -347.0e6]
    assert r["nomes"] == 2 and r["fixa"] == "N"


def test_montar_carrega_os_campos_extras_por_celula():
    colunas = [col(**{"3.01": "Receita"}), col(**{"3.01": "Receita"})]
    valores = [{"3.01": 10.0}, {"3.01": 20.0}]
    extras = {"o": [{"3.01": "publicado"}, {"3.01": "derivado"}],
              "f": [{"3.01": None}, {"3.01": "par_ambiguo"}]}
    r, = server.montar(server.encadear(colunas), colunas, valores, extras)
    assert r["o"] == ["publicado", "derivado"] and r["f"] == [None, "par_ambiguo"]


def test_coluna_unica_e_entrada_vazia():
    assert server.encadear([]) == []
    assert series_de([col(**{"3.01": "Receita"})]) == {"3.01": ["3.01"]}
    assert server.montar([], [], []) == []
