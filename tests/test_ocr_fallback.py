"""Testes unitários para o módulo ocr_fallback (Etapa 9.8)."""
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "ingest"))
from ocr_fallback import (
    ocr_disponivel,
    ocr_imagem_png,
    pagina_precisa_ocr,
    reparar_paginas_com_ocr,
    tesseract_bin,
)


def test_tesseract_bin_and_disponivel():
    # Tesseract está instalado na máquina de teste (homebrew ou path)
    tb = tesseract_bin()
    assert tb is None or isinstance(tb, str)
    disp = ocr_disponivel()
    assert isinstance(disp, bool)


def test_pagina_precisa_ocr():
    # Página vazia precisa
    assert pagina_precisa_ocr("") is True
    assert pagina_precisa_ocr("   \n  ") is True

    # Página com (cid:) precisa
    assert pagina_precisa_ocr("Texto (cid:10) (cid:11) corrompido") is True

    # Página com texto normal em português não precisa
    assert pagina_precisa_ocr(
        "Demonstrações Financeiras da Companhia ABC S.A. referentes ao exercício social findo em 31 de dezembro de 2025. "
        "A receita líquida totalizou R$ 1.500.000 mil, refletindo crescimento orgânico."
    ) is False

    # Página com letras soltas / corrompida precisa
    letras_soltas = "a b c d e f g h i j k l m n o p q r s t u v x z " * 10
    assert pagina_precisa_ocr(letras_soltas) is True


def test_reparar_paginas_sem_problema_retorna_rapido():
    pdf_bytes = b"%PDF-1.4 teste"
    pages = [
        "Página 1 limpa com texto estruturado suficiente para passar.",
        "Página 2 também limpa com notas explicativas normais e legíveis.",
    ]
    novas, reparadas = reparar_paginas_com_ocr(pdf_bytes, pages)
    assert reparadas == 0
    assert novas == pages


def test_reparar_paginas_mock_ocr():
    pdf_bytes = b"%PDF-1.4 teste"
    pages = [
        "Página normal.",
        "(cid:1)(cid:2)(cid:3) texto ilegivel",
    ]

    with patch("ocr_fallback.ocr_disponivel", return_value=True), \
         patch("ocr_fallback.pypdfium2.PdfDocument") as mock_pdf, \
         patch("ocr_fallback.ocr_imagem_png", return_value="Texto recuperado limpo e legível da Nota 10."):
        
        # Simula doc com 2 páginas
        mock_page = MagicMock()
        mock_img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        mock_page.render.return_value.to_pil.return_value = mock_img
        mock_pdf.return_value.__len__.return_value = 2
        mock_pdf.return_value.__getitem__.return_value = mock_page

        novas, reparadas = reparar_paginas_com_ocr(pdf_bytes, pages)
        assert reparadas == 1
        assert novas[0] == "Página normal."
        assert novas[1] == "Texto recuperado limpo e legível da Nota 10."


def test_ocr_imagem_png_real_se_disponivel():
    if not ocr_disponivel():
        pytest.skip("Tesseract não disponível neste ambiente")

    im = Image.new("RGB", (300, 80), color=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    res = ocr_imagem_png(buf.getvalue())
    # Imagem em branco produz texto vazio sem erro
    assert isinstance(res, str)
