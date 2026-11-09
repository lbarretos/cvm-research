"""
Testes do segmentador de notas explicativas e dicionário canônico (Etapa 9, itens 9.10 e 9.11).
"""
import sys
import os
import pytest

# Adiciona scripts ao sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from ingest.secoes_notas import (
    CANONICAS,
    ALIASES,
    SecaoNota,
    normalizar_titulo,
    identificar_secao_canonica,
    resolver_chave_secao,
    eh_linha_tabela_ou_demonstrativo,
    extrair_secoes_documento,
    obter_secao_por_chave,
    encontrar_secao_do_offset,
)


def test_identificar_secao_canonica_todas_as_chaves():
    """Verifica que cada uma das 13 seções canônicas é reconhecida em português e inglês."""
    amostras = {
        "ir_csll": [
            "Provisão para Imposto de Renda e Contribuição Social",
            "Impostos sobre o Lucro",
            "Tributos sobre o lucro líquido",
            "Income taxes",
            "IRPJ e CSLL",
        ],
        "subvencoes": [
            "Subvenções e assistências governamentais",
            "Incentivos fiscais",
            "Benefícios fiscais - Lei do Bem",
            "Incentivos da SUDENE",
            "Government grants",
        ],
        "tributos_recuperar": [
            "Tributos a recuperar",
            "Impostos e contribuições a recuperar",
            "Créditos tributários",
            "Recoverable taxes",
        ],
        "imobilizado": [
            "Imobilizado",
            "Ativo imobilizado",
            "Property, plant and equipment",
            "Fixed assets",
        ],
        "intangivel": [
            "Intangível",
            "Ativos intangíveis e ágio",
            "Goodwill",
            "Intangible assets",
        ],
        "provisoes": [
            "Provisões para contingências",
            "Processos judiciais cíveis e tributários",
            "Litígios e contingências passivas",
            "Provisions and contingencies",
        ],
        "divida_emprestimos": [
            "Empréstimos e financiamentos",
            "Debêntures a pagar",
            "Dívida financeira",
            "Borrowings and loans",
        ],
        "partes_relacionadas": [
            "Partes relacionadas",
            "Transações com partes relacionadas",
            "Related party disclosures",
        ],
        "patrimonio_liquido": [
            "Patrimônio líquido",
            "Capital social e reservas",
            "Shareholders' equity",
        ],
        "segmentos": [
            "Informações por segmento",
            "Segmentos operacionais",
            "Operating segments",
        ],
        "arrendamentos": [
            "Arrendamentos",
            "Direito de uso em arrendamento",
            "Leases",
        ],
        "eventos_subsequentes": [
            "Eventos subsequentes",
            "Fatos posteriores ao encerramento",
            "Subsequent events",
        ],
        "instrumentos_financeiros": [
            "Instrumentos financeiros",
            "Gestão de riscos financeiros",
            "Financial instruments",
        ],
    }

    for chave_esperada, titulos in amostras.items():
        assert chave_esperada in CANONICAS
        for tit in titulos:
            obtido = identificar_secao_canonica(tit)
            assert obtido == chave_esperada, f"Falha para '{tit}': esperado {chave_esperada}, obtido {obtido}"


def test_resolver_chave_secao_apelidos_e_variantes():
    """Testa aliases e variações de escrita de seções."""
    assert resolver_chave_secao("ir_csll") == "ir_csll"
    assert resolver_chave_secao("IR") == "ir_csll"
    assert resolver_chave_secao("impostos") == "ir_csll"
    assert resolver_chave_secao("emprestimos") == "divida_emprestimos"
    assert resolver_chave_secao("divida") == "divida_emprestimos"
    assert resolver_chave_secao("incentivos") == "subvencoes"
    assert resolver_chave_secao("pl") == "patrimonio_liquido"
    assert resolver_chave_secao("arrendamento") == "arrendamentos"
    assert resolver_chave_secao("desconhecido_xyz") is None
    assert resolver_chave_secao(None) is None


def test_eh_linha_tabela_ou_demonstrativo():
    """Identifica linhas com múltiplos valores contábeis de tabelas."""
    assert eh_linha_tabela_ou_demonstrativo("VALOR ADICIONADO BRUTO (1-2) 25.731.236 27.731.743 28.088.64")
    assert eh_linha_tabela_ou_demonstrativo("Lucro líquido antes do IR 10.000 (5.000) 2.000")
    assert not eh_linha_tabela_ou_demonstrativo("26 IMPOSTO DE RENDA E CONTRIBUIÇÃO SOCIAL")
    assert not eh_linha_tabela_ou_demonstrativo("12 Imobilizado")
    assert not eh_linha_tabela_ou_demonstrativo("Nota 16 - Empréstimos e Financiamentos")


def test_extrair_secoes_e_paginas():
    """Testa a extração de seções num texto estruturado simulado com \\f."""
    doc = (
        "Demonstrações Financeiras 2025\n"
        "Balanço Patrimonial...\n"
        "\f"
        "Nota 1 - Contexto Operacional\n"
        "A Companhia opera no setor de bens industriais...\n"
        "\f"
        "Nota 2 - Resumo das Práticas Contábeis\n"
        "2.1 Base de elaboração...\n"
        "2.8 Imobilizado: depreciado pelo método linear.\n"
        "\f"
        "Nota 12 - Imobilizado\n"
        "Composição do ativo imobilizado:\n"
        "Terrenos e Edifícios 100.000\n"
        "\f"
        "Nota 26 - Imposto de Renda e Contribuição Social\n"
        "Conciliação da alíquota efetiva de imposto:\n"
        "Lucro antes dos impostos: 1.000.000\n"
        "Alíquota 34%: (340.000)\n"
        "Incentivos fiscais: 50.000\n"
        "\f"
        "Nota 29 - Subvenções Governamentais\n"
        "A Companhia possui incentivos fiscais estaduais de ICMS...\n"
    )

    secoes = extrair_secoes_documento(doc)
    assert len(secoes) >= 5

    # Nota 1
    s1 = next(s for s in secoes if s.numero == "1")
    assert s1.titulo == "Contexto Operacional"
    assert s1.pagina_inicio == 2

    # Nota 2.8 vs Nota 12 (Imobilizado)
    imob = obter_secao_por_chave(secoes, "imobilizado")
    assert imob is not None
    assert imob.numero == "12"
    assert imob.is_primaria is True
    assert imob.pagina_inicio == 4

    # Nota 26 (IR)
    ir = obter_secao_por_chave(secoes, "ir_csll")
    assert ir is not None
    assert ir.numero == "26"
    assert ir.secao_canonica == "ir_csll"
    assert ir.pagina_inicio == 5
    assert "Imposto de Renda" in ir.titulo

    # Nota 29 (Subvenções)
    sub = obter_secao_por_chave(secoes, "subvencoes")
    assert sub is not None
    assert sub.numero == "29"
    assert sub.pagina_inicio == 6


def test_encontrar_secao_do_offset():
    doc = (
        "Texto introdutório sem nota.\n"
        "Nota 10 - Intangível\n"
        "Conteúdo da nota 10 de intangível...\n"
        "Nota 11 - Provisões para Contingências\n"
        "Conteúdo da nota 11 de provisões judiciais...\n"
    )
    secoes = extrair_secoes_documento(doc)
    assert len(secoes) == 2

    # Offset antes da primeira nota
    assert encontrar_secao_do_offset(secoes, 5) is None

    # Offset dentro da Nota 10
    pos_n10 = doc.find("intangível...")
    s10 = encontrar_secao_do_offset(secoes, pos_n10)
    assert s10 is not None
    assert s10.numero == "10"
    assert s10.secao_canonica == "intangivel"

    # Offset dentro da Nota 11
    pos_n11 = doc.find("provisões judiciais...")
    s11 = encontrar_secao_do_offset(secoes, pos_n11)
    assert s11 is not None
    assert s11.numero == "11"
    assert s11.secao_canonica == "provisoes"

    # Offset além do fim
    assert encontrar_secao_do_offset(secoes, len(doc) + 10) is None
    # Offset negativo
    assert encontrar_secao_do_offset(secoes, -1) is None


def test_extrair_secoes_formatos_variados():
    """Testa diferentes formatos de cabeçalhos: com 'Nota', sem 'Nota', com ponto, com parêntese, romanos."""
    doc = (
        "1. Contexto Operacional\n"
        "Texto da nota 1...\n"
        "26. Imposto de Renda e Contribuição Social\n"
        "Texto de IR...\n"
        "34) Partes Relacionadas\n"
        "Texto partes relacionadas...\n"
        "Nota IV - Instrumentos Financeiros\n"
        "Texto instrumentos...\n"
        "Note 18 - Borrowings and Financing\n"
        "Texto divida em ingles...\n"
    )
    secoes = extrair_secoes_documento(doc)
    nums = [s.numero for s in secoes]
    assert "1" in nums
    assert "26" in nums
    assert "34" in nums
    assert "IV" in nums
    assert "18" in nums

    ir = obter_secao_por_chave(secoes, "ir_csll")
    assert ir is not None and ir.numero == "26"

    pr = obter_secao_por_chave(secoes, "partes_relacionadas")
    assert pr is not None and pr.numero == "34"

    inst = obter_secao_por_chave(secoes, "instrumentos_financeiros")
    assert inst is not None and inst.numero == "IV"

    div = obter_secao_por_chave(secoes, "divida_emprestimos")
    assert div is not None and div.numero == "18"


def test_extrair_secoes_ignora_sumario_pontilhado():
    """Verifica que linhas de sumário compactas com pontilhado não são confundidas com a nota real."""
    doc = (
        "Índice das Notas Explicativas:\n"
        "1 Contexto Operacional ......... 10\n"
        "2 Práticas Contábeis ........... 12\n"
        "26 Imposto de Renda ............ 45\n"
        "\n"
        "Corpo do relatório:\n"
        "Nota 26 - Imposto de Renda e Contribuição Social\n"
        "Conciliação detalhada do imposto de renda com alíquota de 34%...\n"
    )
    secoes = extrair_secoes_documento(doc)
    # Apenas a nota real do corpo deve ser extraída para ir_csll
    ir = obter_secao_por_chave(secoes, "ir_csll")
    assert ir is not None
    assert ir.pos_inicio > doc.find("Corpo do relatório")
    assert "Conciliação detalhada" in doc[ir.pos_inicio:ir.pos_fim]


def test_extrair_secoes_texto_vazio_ou_sem_notas():
    assert extrair_secoes_documento("") == []
    assert extrair_secoes_documento("Apenas um texto qualquer sem cabeçalhos de nota.") == []

