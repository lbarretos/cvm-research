"""Testes da métrica de qualidade de texto por página e por documento (Etapa 9, item 9.7)."""
import json
import os
import sqlite3
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from qualidade_texto import avaliar_pagina, avaliar_documento, pagina_esta_degradada


def test_avaliar_pagina_limpa():
    txt = "A Companhia registrou receita líquida de R$ 10.000 milhões no exercício social encerrado em 2025."
    res = avaliar_pagina(txt)
    assert res["status"] == "ok"
    assert res["cid_pct"] == 0.0
    assert res["soltas_pct"] < 0.10


def test_avaliar_pagina_com_cid():
    # Página com muitos (cid:N)
    txt = "Texto com " + "(cid:1234) " * 20 + "fim da nota."
    res = avaliar_pagina(txt)
    assert res["status"] == "ruim"
    assert res["cid_pct"] > 0.05


def test_avaliar_pagina_letras_soltas():
    # Defeito típico da Tupy (tabela de IR com letras espaçadas)
    txt = "E feImIm ito s fisp o s top o s to c a d d is la n ç a d o s a o re s u lta d oe"
    res = avaliar_pagina(txt)
    assert res["status"] == "ruim"
    assert res["soltas_pct"] > 0.30


def test_avaliar_documento_com_paginas():
    p_ok = "Página limpa e normal com texto contábil padrão. " * 15
    p_bad = "Página com defeito grave: " + ("a b c d e f g h i j k l m n o p q r s t u v x z " * 15)

    # 1 página ruim em 10 páginas = parcial
    texto_parcial = "\x0c".join([p_ok] * 9 + [p_bad])
    status, info_json = avaliar_documento(texto_parcial)
    info = json.loads(info_json)
    assert status == "parcial"
    assert info["total_paginas"] == 10
    assert info["n_ruins"] == 1
    assert info["piores"][0]["pagina"] == 10

    # 1 página ruim em 3 páginas = ruim (33% degradado)
    texto_ruim = f"{p_ok}\x0c{p_bad}\x0c{p_ok}"
    status_ruim, _ = avaliar_documento(texto_ruim)
    assert status_ruim == "ruim"


def test_pagina_esta_degradada():
    info_json = json.dumps({
        "piores": [{"pagina": 5, "status": "ruim"}]
    })
    # Documento globalmente ruim
    assert pagina_esta_degradada(info_json, 1, "ruim") is True

    # Documento parcial, página 5 é ruim
    assert pagina_esta_degradada(info_json, 5, "parcial") is True

    # Documento parcial, página 2 é ok
    assert pagina_esta_degradada(info_json, 2, "parcial") is False

    # Documento ok
    assert pagina_esta_degradada(None, 1, "ok") is False
