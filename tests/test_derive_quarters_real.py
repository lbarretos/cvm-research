"""
Validação da Camada 6 contra o dado bruto da CVM no banco de produção.

Os testes de tests/test_derive_quarters.py usam documentos sintéticos; estes leem
cvm_research.db e conferem, filing a filing, que cada trimestre derivado sai de duas
linhas que são de fato a mesma linha e que a conta fecha. Anos distantes de propósito
(2017, 2021, 2025): o layout das contas criadas pela empresa muda muito ao longo da série.

Pulados quando o banco não está presente (CI, clone novo). Para rodar:
  cd /Users/lucasbarreto/Documents/Coding/cvm-research && .venv/bin/python -m pytest tests/test_derive_quarters_real.py -q
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "analysis"))

from consistency_utils import normalize_text, parent_code, text_similarity

DB = os.environ.get("CVM_DB", os.path.join(os.path.dirname(__file__), "..", "cvm_research.db"))
ANOS = ("2017", "2021", "2025")
# Mistura de perfis: renumeração pesada (MULT3, EQTL3), plano COSIF (ITUB4),
# layout estável (WEGE3) e duas grandes com muitas sublinhas (VALE3, PETR4).
TICKERS = ("MULT3", "EQTL3", "ITUB4", "WEGE3", "VALE3", "PETR4")
MULT = "07.816.890/0001-53"

pytestmark = pytest.mark.skipif(not os.path.exists(DB), reason=f"banco de produção ausente em {DB}")


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    yield c
    c.close()


@pytest.fixture(scope="module", autouse=True)
def camada6_rodou(conn):
    """A base pode ser de qualquer um que clonou o repositório. Se a Camada 6 ainda não
    rodou, não há o que validar: pula com a instrução em vez de acusar falha."""
    n = conn.execute("SELECT COUNT(*) FROM demonstrativos_trimestrais").fetchone()[0]
    if not n:
        pytest.skip("demonstrativos_trimestrais vazia — rode `run_all.py --layer 6 --full` antes")


@pytest.fixture(scope="module")
def cnpjs(conn):
    """Só as empresas da amostra que existem nesta base. Uma watchlist diferente da nossa
    é legítima: valida o que der e pula se não sobrar nenhuma."""
    achados = {t: c for t, c in conn.execute(
        f"SELECT ticker, cnpj FROM companies WHERE ticker IN ({','.join('?' * len(TICKERS))})", TICKERS)}
    if not achados:
        pytest.skip(f"nenhuma das empresas da amostra está na watchlist: {', '.join(TICKERS)}")
    return achados


def _derivadas(conn, cnpj):
    """Linhas de demonstrativos_trimestrais com valor derivado nos anos de interesse."""
    return conn.execute(f"""
        SELECT tipo_doc, safra, exercicio_ini, trimestre, cd_conta, ds_conta, cd_conta_b, casamento,
               vl_derivado, fonte_a, data_a, ordem_a, fonte_b, data_b, ordem_b
        FROM demonstrativos_trimestrais
        WHERE cnpj_companhia = ? AND trimestre > 1 AND vl_derivado IS NOT NULL
          AND substr(dt_fim_exerc, 1, 4) IN ({','.join('?' * len(ANOS))})
        ORDER BY tipo_doc, safra, exercicio_ini, trimestre, cd_conta""", (cnpj, *ANOS)).fetchall()


def _acumulado(conn, cnpj, tipo_doc, fonte, data_ref, ordem):
    """{cd_conta: (ds_conta, vl_conta)} do acumulado (menor dt_ini_exerc) de um filing,
    na versão máxima — o mesmo recorte que consistency_utils.latest_rows faz."""
    linhas = conn.execute("""
        SELECT cd_conta, ds_conta, vl_conta, dt_ini_exerc FROM demonstrativos_contabeis
        WHERE cnpj_companhia = ? AND tipo_doc = ? AND fonte = ? AND data_referencia = ? AND ordem_exercicio = ?
          AND versao = (SELECT MAX(versao) FROM demonstrativos_contabeis
                        WHERE cnpj_companhia = ? AND tipo_doc = ? AND fonte = ? AND data_referencia = ?)
        """, (cnpj, tipo_doc, fonte, data_ref, ordem, cnpj, tipo_doc, fonte, data_ref)).fetchall()
    inicios = [r[3] for r in linhas if r[3] is not None]
    if not inicios:
        return {}
    ini = min(inicios)
    out = {}
    for cd, ds, vl, dt_ini in linhas:
        if dt_ini == ini:
            out.setdefault(cd, (ds, vl))
    return out


def test_todo_derivado_bate_com_a_subtracao_do_bruto(conn, cnpjs):
    """vl_derivado == vl_conta(A, cd_conta) − vl_conta(B, cd_conta_b), lido do dado bruto."""
    conferidas = 0
    erros = []
    for ticker, cnpj in cnpjs.items():
        cache = {}
        for r in _derivadas(conn, cnpj):
            (tipo, _safra, _ex, tri, cd, _ds, cd_b, casamento, vl, fa, da, oa, fb, db, ob) = r
            assert cd_b and casamento, f"{ticker} {tipo} {da} {cd}: derivou sem registrar o par"
            for chave in ((tipo, fa, da, oa), (tipo, fb, db, ob)):
                if chave not in cache:
                    cache[chave] = _acumulado(conn, cnpj, *chave)
            va = cache[(tipo, fa, da, oa)].get(cd)
            vb = cache[(tipo, fb, db, ob)].get(cd_b)
            assert va and vb, f"{ticker} {tipo} {da} {cd}: par {cd_b} não está no bruto"
            esperado = (va[1] or 0.0) - (vb[1] or 0.0)
            if abs(vl - esperado) > 0.01:
                erros.append(f"{ticker} {tipo} {da} T{tri} {cd}: gravado {vl:,.2f} ≠ bruto {esperado:,.2f}")
            conferidas += 1
    assert not erros, "\n".join(erros[:20])
    assert conferidas, "nenhuma linha derivada nos anos da amostra nesta base"


def test_nenhum_derivado_casa_linhas_de_conteudo_diferente(conn, cnpjs):
    """A regressão original: subtrair 'Dividendos' de 'Pagamento de encargos'.
    Todo par usado tem nome igual (normalizado) ou similaridade >= 0.75."""
    erros = []
    for ticker, cnpj in cnpjs.items():
        cache = {}
        for r in _derivadas(conn, cnpj):
            (tipo, _safra, _ex, _tri, cd, ds, cd_b, casamento, _vl, _fa, da, _oa, fb, db, ob) = r
            assert casamento != "ambiguo", f"{ticker} {tipo} {da} {cd}: par ambíguo não pode derivar"
            if (tipo, fb, db, ob) not in cache:
                cache[(tipo, fb, db, ob)] = _acumulado(conn, cnpj, tipo, fb, db, ob)
            ds_b = cache[(tipo, fb, db, ob)][cd_b][0]
            if normalize_text(ds) == normalize_text(ds_b):
                continue
            # text_similarity é assimétrica (difflib): a ordem tem de ser a mesma que
            # _comparar_pai usa, (anterior, atual), senão o score cai abaixo do limiar
            # em pares legítimos e o teste acusa erro que não existe.
            score = text_similarity(ds_b, ds)
            if score < 0.75:
                erros.append(f"{ticker} {tipo} {da} {cd} '{ds}' ← {cd_b} '{ds_b}' (score {score:.2f}, casamento {casamento})")
    assert not erros, f"{len(erros)} pares de conteúdo diferente:\n" + "\n".join(erros[:20])


def test_oraculo_independente_por_nome_unico(conn, cnpjs):
    """Checagem sem usar a escada de similaridade: quando um nome normalizado é único
    nos dois acumulados E está sob o mesmo pai, o subtraendo correto é inequívoco.
    A Camada 6 tem de concordar. O recorte pelo pai é necessário porque o casamento é
    hierárquico: um pai renumerado leva os filhos junto, e aí o código do pai muda dos
    dois lados — nesses casos o oráculo não se aplica e a linha é pulada."""
    conferidas = 0
    erros = []
    for ticker, cnpj in cnpjs.items():
        cache = {}
        for r in _derivadas(conn, cnpj):
            (tipo, _safra, _ex, _tri, cd, ds, cd_b, _cas, _vl, fa, da, oa, fb, db, ob) = r
            for chave in ((tipo, fa, da, oa), (tipo, fb, db, ob)):
                if chave not in cache:
                    cache[chave] = _acumulado(conn, cnpj, *chave)
            alvo = normalize_text(ds)
            if not alvo:
                continue
            em_a = [c for c, (d, _v) in cache[(tipo, fa, da, oa)].items() if normalize_text(d) == alvo]
            em_b = [c for c, (d, _v) in cache[(tipo, fb, db, ob)].items()
                    if normalize_text(d) == alvo and parent_code(c) == parent_code(cd)]
            if len(em_a) != 1 or len(em_b) != 1:
                continue                                   # nome repetido, ausente ou pai diferente
            if em_b[0] != cd_b:
                erros.append(f"{ticker} {tipo} {da} {cd} '{ds}': casou com {cd_b}, nome único aponta {em_b[0]}")
            conferidas += 1
    assert not erros, f"{len(erros)} divergências do oráculo:\n" + "\n".join(erros[:20])
    assert conferidas, "o oráculo não encontrou nenhuma linha de nome único nesta base"


def test_multiplan_6_03_08_regressao_relatada(conn):
    """O caso que originou a correção: 6.03.08 da DFC virou dividendo no 1T e encargos
    de debêntures no 2T, e o DFP manteve 'Aumento de capital social' no mesmo código.

    Valores presos a um retrato do dado (ITRs de 2026 e DFP de 2025 como publicados em
    18/09/2026). Numa base montada em outra data, ou sem a Multiplan na watchlist, não há
    o que comparar: pula. Os outros testes deste arquivo valem para qualquer base."""
    if not conn.execute("SELECT 1 FROM companies WHERE cnpj = ?", (MULT,)).fetchone():
        pytest.skip("Multiplan não está na watchlist desta base")
    for ex, tri in (("2026-01-01", 2), ("2025-01-01", 4)):
        achou = conn.execute("""SELECT 1 FROM demonstrativos_trimestrais
                                WHERE cnpj_companhia=? AND tipo_doc='DFC_MI' AND safra='original'
                                  AND exercicio_ini=? AND trimestre=?""", (MULT, ex, tri)).fetchone()
        if not achou:
            pytest.skip(f"esta base não tem o {tri}T do exercício {ex[:4]} da Multiplan")
    q = dict(((r[0], r[1]), r[2:]) for r in conn.execute("""
        SELECT trimestre, cd_conta, ds_conta, cd_conta_b, casamento, vl_derivado, vl_final, flag
        FROM demonstrativos_trimestrais
        WHERE cnpj_companhia = ? AND tipo_doc = 'DFC_MI' AND safra = 'original'
          AND exercicio_ini = '2026-01-01' AND cd_conta LIKE '6.03.%'""", (MULT,)))
    ds, cd_b, cas, vl, final, flag = q[(2, "6.03.08")]
    assert ds == "Pagamento de encargos sobre debêntures"
    assert (cd_b, cas, flag) == ("6.03.06", "reformulacao", None)
    assert round(final / 1e6, 1) == -202.1                 # −347,0 − (−144,9); antes gravava −249,5
    ds, cd_b, cas, vl, final, flag = q[(2, "6.03.09")]
    assert (cd_b, cas) == ("6.03.08", "reformulacao") and round(final / 1e6, 1) == -105.9
    ds, cd_b, cas, vl, final, flag = q[(2, "6.03.06")]                 # "Pagamento de debêntures" é linha nova
    assert (ds, vl, final, flag) == ("Pagamento de debêntures", None, None, "linha_sem_par")

    q25 = dict(((r[0], r[1]), r[2:]) for r in conn.execute("""
        SELECT trimestre, cd_conta, ds_conta, cd_conta_b, casamento, vl_derivado, vl_final, flag
        FROM demonstrativos_trimestrais
        WHERE cnpj_companhia = ? AND tipo_doc = 'DFC_MI' AND safra = 'original'
          AND exercicio_ini = '2025-01-01' AND trimestre = 4 AND cd_conta LIKE '6.03.%'""", (MULT,)))
    ds, cd_b, cas, vl, final, flag = q25[(4, "6.03.07")]
    assert (ds, cd_b, cas) == ("Pagamento de encargos sobre debêntures", "6.03.08", "renumerado")
    assert round(final / 1e6, 1) == -207.6                 # −560,1 − (−352,5)
    ds, cd_b, cas, vl, final, flag = q25[(4, "6.03.08")]
    assert ds == "Aumento de capital social"
    assert (vl, final, flag) == (None, None, "linha_sem_par")   # antes gravava +352,5


def test_par_ambiguo_e_fila_de_revisao_nao_valor(conn):
    """Nenhum 'par_ambiguo' tem valor, e cada um deixa o candidato registrado."""
    assert conn.execute("""SELECT COUNT(*) FROM demonstrativos_trimestrais
                           WHERE flag = 'par_ambiguo' AND vl_derivado IS NOT NULL""").fetchone()[0] == 0
    n_linhas = conn.execute("SELECT COUNT(*) FROM demonstrativos_trimestrais WHERE flag = 'par_ambiguo'").fetchone()[0]
    n_flags = conn.execute("""SELECT COUNT(*) FROM consistency_flags
                              WHERE layer = 6 AND classificacao = 'par_ambiguo'""").fetchone()[0]
    assert n_linhas == n_flags          # uma flag por linha bloqueada; zero é legítimo numa base pequena
    faltando = conn.execute("""SELECT COUNT(*) FROM consistency_flags WHERE layer = 6 AND classificacao = 'par_ambiguo'
                               AND (json_extract(detalhe, '$.cd_conta_b') IS NULL
                                    OR json_extract(detalhe, '$.score') IS NULL)""").fetchone()[0]
    assert faltando == 0
