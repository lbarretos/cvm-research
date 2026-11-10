"""Módulo de fallback com OCR seletivo para PDFs com fontes corrompidas ou escaneados (Etapa 9.8).

Utiliza:
- pypdfium2 (renderização rápida da página em memória para PNG)
- tesseract (OCR executado via stdin -> stdout, sem arquivos intermediários em disco)
- qualidade_texto (avaliação de ganho métrico antes de substituir o texto da página)
"""
import io
import os
import shutil
import subprocess
from typing import Optional

try:
    import pypdfium2
except ImportError:
    pypdfium2 = None

from qualidade_texto import avaliar_pagina


def tesseract_bin() -> Optional[str]:
    """Retorna o caminho do executável do Tesseract ou None se indisponível."""
    bin_path = shutil.which("tesseract")
    if bin_path:
        return bin_path
    for fallback in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"):
        if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
            return fallback
    return None


def ocr_disponivel() -> bool:
    """Verifica se as dependências (pypdfium2 e tesseract) estão prontas para uso."""
    if pypdfium2 is None:
        return False
    bin_path = tesseract_bin()
    if not bin_path:
        return False
    try:
        res = subprocess.run([bin_path, "--version"], capture_output=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def ocr_imagem_png(png_bytes: bytes, lang: str = "por+eng", timeout: int = 30) -> str:
    """Executa o tesseract via stdin/stdout diretamente em memória."""
    bin_path = tesseract_bin()
    if not bin_path:
        return ""
    try:
        proc = subprocess.run(
            [bin_path, "stdin", "stdout", "-l", lang],
            input=png_bytes,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
        return proc.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def pagina_precisa_ocr(texto_pagina: str) -> bool:
    """Retorna True se a página tem fonte corrompida (Identity-H), caracteres ilegíveis ou está vazia."""
    stripped = texto_pagina.strip()
    if not stripped:
        return True
    if "(cid:" in texto_pagina:
        return True
    m = avaliar_pagina(texto_pagina)
    if m["status"] == "ruim":
        return True
    return False


def reparar_paginas_com_ocr(
    conteudo_pdf: bytes,
    pages_text: list[str],
    max_paginas: int = 40,
    lang: str = "por+eng",
) -> tuple[list[str], int]:
    """Inspeciona as páginas extraídas e executa OCR apenas nas que apresentarem degradação.
    
    Substitui o texto da página se o OCR obtiver melhor classificação de qualidade ou mais caracteres úteis.
    Retorna (novas_paginas, total_reparadas).
    """
    if not ocr_disponivel() or not conteudo_pdf.startswith(b"%PDF"):
        return pages_text, 0

    indices_problema = [i for i, txt in enumerate(pages_text) if pagina_precisa_ocr(txt)]
    if not indices_problema:
        return pages_text, 0

    novas_paginas = list(pages_text)
    reparadas = 0

    try:
        doc = pypdfium2.PdfDocument(conteudo_pdf)
    except Exception:
        return pages_text, 0

    total_doc_pages = len(doc)
    for idx in indices_problema[:max_paginas]:
        if idx >= total_doc_pages:
            continue
        try:
            page = doc[idx]
            # scale=2.0 corresponde a aproximadamente 150-200 DPI, equilíbrio ideal velocidade x qualidade
            pil_image = page.render(scale=2.0).to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            ocr_txt = ocr_imagem_png(buf.getvalue(), lang=lang)

            if not ocr_txt.strip():
                continue

            m_orig = avaliar_pagina(novas_paginas[idx])
            m_ocr = avaliar_pagina(ocr_txt)

            # Critério de substituição:
            # 1. Original continha (cid:) e OCR eliminou ou reduziu drasticamente
            # 2. Status do OCR é melhor ('ok' vs 'ruim'/'parcial')
            # 3. Original estava vazio e OCR encontrou texto
            orig_cid = novas_paginas[idx].count("(cid:")
            ocr_cid = ocr_txt.count("(cid:")

            melhorou = False
            if orig_cid > 0 and ocr_cid == 0:
                melhorou = True
            elif m_orig["status"] == "ruim" and m_ocr["status"] in ("ok", "parcial"):
                melhorou = True
            elif not novas_paginas[idx].strip() and len(ocr_txt.strip()) > 50:
                melhorou = True
            elif m_orig["status"] == "parcial" and m_ocr["status"] == "ok":
                melhorou = True

            if melhorou:
                novas_paginas[idx] = ocr_txt
                reparadas += 1
        except Exception:
            continue

    return novas_paginas, reparadas


def ocr_pdf_completo(
    conteudo_pdf: bytes,
    max_paginas: int = 40,
    lang: str = "por+eng",
) -> list[str]:
    """Executa OCR em todas as páginas de um PDF (usado quando pdfplumber não extrai nada)."""
    if not ocr_disponivel() or not conteudo_pdf.startswith(b"%PDF"):
        return []

    try:
        doc = pypdfium2.PdfDocument(conteudo_pdf)
    except Exception:
        return []

    paginas = []
    n_pages = min(len(doc), max_paginas)
    for idx in range(n_pages):
        try:
            page = doc[idx]
            pil_image = page.render(scale=2.0).to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            paginas.append(ocr_imagem_png(buf.getvalue(), lang=lang))
        except Exception:
            paginas.append("")

    return paginas
