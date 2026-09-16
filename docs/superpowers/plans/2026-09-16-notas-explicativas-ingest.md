# Ingestão de Notas Explicativas (ITR/DFP) Implementation Plan

> **Status: IMPLEMENTADO em 2026-09-16** (commits 03f587c → 63fb6e0 na `main`). Mantido como registro de design — em especial a verificação manual de que as notas explicativas só existem no PDF do pacote ZIP da CVM, não no XML. Os checkboxes abaixo não foram atualizados; a fonte da verdade é o código em `scripts/ingest/ingest_notas_explicativas.py`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar um ingestor que baixa e extrai o texto das Notas Explicativas de ITR/DFP da CVM (movimentação de Imobilizado/Intangível/Direito de Uso, provisões, etc.) — dado hoje **inexistente** em `demonstrativos_contabeis` e em `ipe_docs`, e que só existe como PDF dentro do pacote oficial de cada filing.

**Architecture:** O CSV de metadados que `download_year()` já baixa (`{fonte}_cia_aberta_{ano}.csv`, hoje ignorado pelo pipeline) tem uma coluna `ID_DOC` = `NumeroSequencialDocumento`. Baixando `https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx?CodigoInstituicao=1&NumeroSequencialDocumento={ID_DOC}` obtém-se um ZIP oficial contendo (entre outros) o PDF completo do ITR/DFP — o mesmo documento publicado em RI (mziq.com etc.). Extrai-se o texto desse PDF com `pdfplumber` (mesma lib já usada em `extract_pdf.py`) e persiste-se numa tabela nova, com a mesma politica de "nenhum PDF em disco" e o mesmo padrão de FTS5 já usado em `ipe_docs`.

**Confirmado por inspeção manual (não é suposição):** o pacote ZIP do ITR 1T26 da Frasle (`NumeroSequencialDocumento=156792`) contém `006211ITR31-03-2026v2.xml` — um XML proprietário da CVM (não XBRL) com o mesmo schema `Conta/CodigoConta/Valor` já normalizado em `demonstrativos_contabeis` — e **nenhum bloco de nota explicativa**. As notas só existem no PDF embutido (`156792_006211_....pdf`, 85 páginas) — mesmo texto que já validamos manualmente contra os valores de D&A por classe de ativo (Imobilizado/Intangível/Direito de Uso) da Frasle.

**Tech Stack:** Python 3, `pandas`, `httpx` (via `utils._http_get`), `pdfplumber`, `sqlite3`, `pytest` + `unittest.mock`.

---

## File Structure

- **Modify:** `schema.sql` — adiciona tabela `notas_explicativas` + `notas_explicativas_fts` (virtual FTS5).
- **Modify:** `scripts/ingest/utils.py` — adiciona `fetch_doc_metadata(year, fonte)`.
- **Modify:** `tests/test_ingest_transform.py` — testes de `fetch_doc_metadata`.
- **Create:** `scripts/ingest/ingest_notas_explicativas.py` — novo ingestor (download → extração PDF → upsert → FTS).
- **Create:** `tests/test_ingest_notas_explicativas.py` — testes das funções puras e das operações SQLite do novo ingestor (tudo mockado, sem rede).
- **Modify:** `CLAUDE.md` — documenta o novo script na seção "Atualização manual dos dados".

Nenhum arquivo existente precisa ser reestruturado — o novo ingestor segue exatamente o padrão de `extract_pdf.py` (download em memória → extrai → salva → descarta).

---

### Task 1: Schema — tabela `notas_explicativas`

**Files:**
- Modify: `schema.sql` (adicionar ao final, antes da seção `-- ── Views ──`)

- [ ] **Step 1: Adicionar as tabelas ao schema.sql**

Abra `schema.sql`, localize a linha `-- ── Views ─────...` (é o fim da seção de tabelas) e insira **antes** dela:

```sql
-- ── Notas Explicativas (ITR/DFP) ────────────────────────────────────────────
-- Texto completo extraído do PDF oficial do ITR/DFP (o mesmo documento
-- publicado em RI). Não existe em demonstrativos_contabeis: aquela tabela só
-- tem os quadros padronizados (BPA/BPP/DRE/DFC_MI/DVA), sem notas.
-- Ver scripts/ingest/ingest_notas_explicativas.py para o fluxo de extração.

CREATE TABLE IF NOT EXISTS notas_explicativas (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_companhia               TEXT NOT NULL,
    fonte                        TEXT NOT NULL CHECK (fonte IN ('ITR', 'DFP')),
    data_referencia              TEXT NOT NULL,
    versao                       INTEGER NOT NULL DEFAULT 1,
    numero_sequencial_documento  INTEGER NOT NULL,
    link_download                TEXT,
    texto_extraido               TEXT,
    extraido_em                  TEXT,
    extracao_falhou              INTEGER DEFAULT 0,
    chars_extraidos              INTEGER,
    created_at                   TEXT DEFAULT (datetime('now')),
    updated_at                   TEXT DEFAULT (datetime('now')),
    UNIQUE (cnpj_companhia, fonte, data_referencia)
);

CREATE INDEX IF NOT EXISTS idx_notas_cnpj_data ON notas_explicativas (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_notas_sem_texto ON notas_explicativas (cnpj_companhia)
    WHERE texto_extraido IS NULL AND extracao_falhou = 0;

-- Busca full-text (idêntico ao padrão de ipe_docs_fts):
--   INSERT INTO notas_explicativas_fts(notas_explicativas_fts) VALUES ('rebuild');
--   SELECT n.* FROM notas_explicativas_fts f JOIN notas_explicativas n ON n.id = f.rowid
--   WHERE notas_explicativas_fts MATCH 'imobilizado AND depreciacao' ORDER BY rank LIMIT 20;
CREATE VIRTUAL TABLE IF NOT EXISTS notas_explicativas_fts USING fts5(
    cnpj_companhia,
    texto_extraido,
    content='notas_explicativas',
    content_rowid='id'
);
```

- [ ] **Step 2: Aplicar a migração no banco já existente**

Como toda `CREATE TABLE`/`CREATE INDEX` usa `IF NOT EXISTS`, rodar o `schema.sql` inteiro de novo é seguro e idempotente — não recria nem apaga nada que já existe:

```bash
sqlite3 cvm_research.db < schema.sql
```

Run e verifique que a tabela foi criada:

```bash
sqlite3 cvm_research.db ".tables" | grep notas
```

Expected: `notas_explicativas` e `notas_explicativas_fts` (mais as tabelas auxiliares `notas_explicativas_fts_data`, `_idx`, `_docsize`, `_config` que o SQLite cria automaticamente para toda tabela FTS5).

- [ ] **Step 3: Commit**

```bash
git add schema.sql
git commit -m "feat: adiciona tabela notas_explicativas (texto completo de ITR/DFP)"
```

---

### Task 2: `utils.fetch_doc_metadata` — acesso ao ID_DOC/NumeroSequencialDocumento

**Files:**
- Modify: `scripts/ingest/utils.py` (adicionar após `download_year`, fim do arquivo)
- Test: `tests/test_ingest_transform.py`

- [ ] **Step 1: Escrever o teste (vai falhar — função não existe)**

Adicione ao final de `tests/test_ingest_transform.py`:

```python
# ── fetch_doc_metadata ────────────────────────────────────────────────────────

@patch("utils._http_get")
def test_fetch_doc_metadata_retorna_colunas_esperadas(mock_http_get):
    """
    fetch_doc_metadata deve baixar o CSV principal (não os _con_/_ind_) do ZIP
    anual e retornar só as colunas necessárias para localizar o documento
    completo: CNPJ_CIA, DT_REFER, VERSAO, ID_DOC (= NumeroSequencialDocumento).
    """
    import io
    import zipfile

    csv_bytes = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
        "88.610.126/0001-29;2026-03-31;2;FRASLE MOBILITY S.A.;006211;ITR;156792;"
        "2026-05-07;http://x\n"
    ).encode("latin-1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("itr_cia_aberta_2026.csv", csv_bytes)
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    df = fetch_doc_metadata(2026, "ITR")

    assert list(df.columns) == ["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"]
    assert df.iloc[0]["ID_DOC"] == "156792"
    assert df.iloc[0]["CNPJ_CIA"] == "88.610.126/0001-29"
    mock_http_get.assert_called_once_with(
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip",
        timeout=300,
    )


@patch("utils._http_get")
def test_fetch_doc_metadata_dfp_usa_url_dfp(mock_http_get):
    """fonte='DFP' deve montar a URL do ZIP anual de DFP, não de ITR."""
    import io
    import zipfile

    csv_bytes = "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n".encode("latin-1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dfp_cia_aberta_2025.csv", csv_bytes)
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    fetch_doc_metadata(2025, "DFP")

    mock_http_get.assert_called_once_with(
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2025.zip",
        timeout=300,
    )
```

No topo do arquivo, atualize o import existente para incluir a nova função:

```python
from utils import _date, _float, _http_get, _int, _sanitize, _upsert_sqlite, upsert, get_db, fetch_doc_metadata
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_transform.py -k fetch_doc_metadata -v`
Expected: `ImportError: cannot import name 'fetch_doc_metadata'`

- [ ] **Step 3: Implementar `fetch_doc_metadata`**

Adicione ao final de `scripts/ingest/utils.py`:

```python
def fetch_doc_metadata(year: int, fonte: str) -> pd.DataFrame:
    """
    Baixa o CSV principal (não os _con_/_ind_) do ZIP anual de DFP/ITR.

    Esse CSV traz ID_DOC (= NumeroSequencialDocumento) e LINK_DOC por
    (CNPJ_CIA, DT_REFER, VERSAO) — é o único ponto de acesso ao pacote
    ZIP completo do documento, que contém o PDF com as Notas Explicativas.
    Os CSVs _con_/_ind_ (consumidos por download_year) não têm essa
    informação; só o CSV principal do ZIP tem.

    Ver ingest_notas_explicativas.py para o consumidor.

    Colunas retornadas: CNPJ_CIA, DT_REFER, VERSAO, ID_DOC (todas como string,
    dtype=str — conversão para int fica a cargo do chamador).
    """
    source = fonte.lower()
    url = (
        f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{fonte}/DADOS/"
        f"{source}_cia_aberta_{year}.zip"
    )
    r = _http_get(url, timeout=300)
    fname = f"{source}_cia_aberta_{year}.csv"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(fname) as f:
            df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)
    return df[["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"]]
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_transform.py -k fetch_doc_metadata -v`
Expected: `2 passed`

- [ ] **Step 5: Rodar a suíte inteira para garantir que nada quebrou**

Run: `cd scripts/ingest && python -m pytest ../../tests/ -v`
Expected: todos os testes existentes + os 2 novos passam.

- [ ] **Step 6: Commit**

```bash
git add scripts/ingest/utils.py tests/test_ingest_transform.py
git commit -m "feat: adiciona utils.fetch_doc_metadata (ID_DOC/NumeroSequencialDocumento)"
```

---

### Task 3: `ingest_notas_explicativas.py` — funções puras (sem rede, sem banco)

**Files:**
- Create: `scripts/ingest/ingest_notas_explicativas.py` (esqueleto + 2 funções puras)
- Create: `tests/test_ingest_notas_explicativas.py`

- [ ] **Step 1: Escrever os testes das funções puras**

Crie `tests/test_ingest_notas_explicativas.py`:

```python
"""
Testes do ingestor de Notas Explicativas (ITR/DFP).

Cobre:
  - latest_por_periodo: reduz o CSV de metadados a 1 linha por (cnpj, período),
    escolhendo sempre a maior VERSAO.
  - extrair_pdf_do_pacote: acha o PDF dentro do ZIP do pacote do documento.
  - Operações SQLite: _upsert_pendente_rows, _fetch_pendentes, _salvar.
  - fetch_notas_texto: download + extração de texto, com rede e pdfplumber mockados.
"""
import io
import sqlite3
import sys
import os
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "ingest"))

from ingest_notas_explicativas import (
    latest_por_periodo,
    extrair_pdf_do_pacote,
    fetch_notas_texto,
    _upsert_pendente_rows,
    _fetch_pendentes,
    _salvar,
)


# ── latest_por_periodo ────────────────────────────────────────────────────────

def test_latest_por_periodo_escolhe_maior_versao():
    df = pd.DataFrame([
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "156716"},
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "2", "ID_DOC": "156792"},
    ])
    result = latest_por_periodo(df, {"88.610.126/0001-29"}, fonte="ITR")

    assert result == [{
        "cnpj_companhia": "88.610.126/0001-29",
        "fonte": "ITR",
        "data_referencia": "2026-03-31",
        "versao": 2,
        "numero_sequencial_documento": 156792,
    }]


def test_latest_por_periodo_filtra_por_watchlist():
    df = pd.DataFrame([
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "156792"},
        {"CNPJ_CIA": "00.000.000/0001-91", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "999"},
    ])
    result = latest_por_periodo(df, {"88.610.126/0001-29"}, fonte="ITR")

    assert len(result) == 1
    assert result[0]["cnpj_companhia"] == "88.610.126/0001-29"


def test_latest_por_periodo_multiplos_periodos_mesma_empresa():
    df = pd.DataFrame([
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2025-12-31", "VERSAO": "1", "ID_DOC": "111"},
        {"CNPJ_CIA": "88.610.126/0001-29", "DT_REFER": "2026-03-31", "VERSAO": "1", "ID_DOC": "222"},
    ])
    result = latest_por_periodo(df, {"88.610.126/0001-29"}, fonte="ITR")

    assert len(result) == 2
    periodos = {r["data_referencia"] for r in result}
    assert periodos == {"2025-12-31", "2026-03-31"}


# ── extrair_pdf_do_pacote ─────────────────────────────────────────────────────

def test_extrair_pdf_do_pacote_encontra_pdf():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("006211ITR31-03-2026v2.xml", b"<xml/>")
        z.writestr("156792_006211_ts.pdf", b"%PDF-1.4 conteudo fake")
        z.writestr("DadosDocumento.xlsx", b"fake xlsx")

    pdf_bytes = extrair_pdf_do_pacote(buf.getvalue())

    assert pdf_bytes == b"%PDF-1.4 conteudo fake"


def test_extrair_pdf_do_pacote_sem_pdf_retorna_none():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apenas.xml", b"<xml/>")

    assert extrair_pdf_do_pacote(buf.getvalue()) is None
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_notas_explicativas.py -v`
Expected: `ModuleNotFoundError: No module named 'ingest_notas_explicativas'`

- [ ] **Step 3: Criar o esqueleto do módulo com as 2 funções puras**

Crie `scripts/ingest/ingest_notas_explicativas.py`:

```python
"""
Extrai o texto das Notas Explicativas de ITR/DFP da CVM.

Por que este script existe: demonstrativos_contabeis (ingest_dfp.py /
ingest_itr.py) só tem os quadros padronizados (BPA/BPP/DRE/DFC_MI/DVA) — sem
notas explicativas. Confirmado por inspeção manual do pacote ZIP oficial de um
ITR (Frasle 1T26, NumeroSequencialDocumento=156792): o XML embutido
("006211ITR31-03-2026v2.xml") usa o mesmo schema Conta/CodigoConta/Valor já
normalizado no banco — não é XBRL e não tem nenhum bloco de nota. As notas só
existem no PDF completo embutido no mesmo pacote (mesmo documento publicado em
sites de RI como mziq.com).

Fluxo: utils.fetch_doc_metadata() dá o NumeroSequencialDocumento por
(cnpj, data_referencia) → baixa o ZIP do pacote em memória → extrai o PDF
embutido em memória → extrai texto com pdfplumber → salva no banco → descarta
os bytes. Nenhum PDF é persistido em disco (mesma política de extract_pdf.py).

Uso:
  python ingest_notas_explicativas.py --cnpj 88.610.126/0001-29 --ano 2026 --fonte ITR
  python ingest_notas_explicativas.py --ano 2025 --fonte DFP
  python ingest_notas_explicativas.py --ano 2025 --fonte ITR --limite 20
  python ingest_notas_explicativas.py --retry-failed
  python ingest_notas_explicativas.py --rebuild-fts

Requer DATABASE_URL=sqlite:///cvm_research.db no .env.
"""
import argparse
import io
import time
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import pdfplumber

from utils import _http_get, fetch_doc_metadata, get_db, watchlist_cnpjs

DOWNLOAD_URL = (
    "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
    "?CodigoInstituicao=1&NumeroSequencialDocumento={numero}"
)


# ── Funções puras ─────────────────────────────────────────────────────────────

def latest_por_periodo(df_meta: pd.DataFrame, cnpjs: set, fonte: str) -> list[dict]:
    """
    Reduz o CSV de metadados (ver utils.fetch_doc_metadata) a 1 linha por
    (cnpj, data_referencia): a maior VERSAO — igual à lógica já usada nas
    queries de demonstrativos_contabeis (CLAUDE.md, seção "DRE linha a linha").
    """
    df = df_meta[df_meta["CNPJ_CIA"].isin(cnpjs)].copy()
    if df.empty:
        return []
    df["VERSAO"] = df["VERSAO"].astype(int)
    df["ID_DOC"] = df["ID_DOC"].astype(int)
    df = df.sort_values("VERSAO").drop_duplicates(
        subset=["CNPJ_CIA", "DT_REFER"], keep="last"
    )
    return [
        {
            "cnpj_companhia": r["CNPJ_CIA"],
            "fonte": fonte,
            "data_referencia": r["DT_REFER"],
            "versao": int(r["VERSAO"]),
            "numero_sequencial_documento": int(r["ID_DOC"]),
        }
        for _, r in df.iterrows()
    ]


def extrair_pdf_do_pacote(zip_bytes: bytes) -> bytes | None:
    """Retorna os bytes do primeiro .pdf dentro do pacote ZIP do documento."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        pdf_names = [n for n in z.namelist() if n.lower().endswith(".pdf")]
        if not pdf_names:
            return None
        return z.read(pdf_names[0])


if __name__ == "__main__":
    pass  # CLI adicionado na Task 6
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_notas_explicativas.py -v`
Expected: `5 passed` (os 3 de `latest_por_periodo` + 2 de `extrair_pdf_do_pacote`; os testes de `fetch_notas_texto` e das operações SQLite ainda falham por import — normal, vêm nas próximas tasks)

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest/ingest_notas_explicativas.py tests/test_ingest_notas_explicativas.py
git commit -m "feat: funções puras do ingestor de notas explicativas"
```

---

### Task 4: Download + extração de PDF (`fetch_notas_texto`)

**Files:**
- Modify: `scripts/ingest/ingest_notas_explicativas.py`
- Modify: `tests/test_ingest_notas_explicativas.py`

- [ ] **Step 1: Escrever os testes (vão falhar — `fetch_notas_texto` ainda não existe)**

Adicione a `tests/test_ingest_notas_explicativas.py`:

```python
# ── fetch_notas_texto ─────────────────────────────────────────────────────────

@patch("ingest_notas_explicativas.pdfplumber.open")
@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_sucesso(mock_http_get, mock_pdf_open):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("156792_006211_ts.pdf", b"%PDF-1.4 fake")
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    page = MagicMock()
    page.extract_text.return_value = "Despesa de depreciação do período (26.581)"
    mock_pdf_open.return_value.__enter__.return_value.pages = [page]

    texto = fetch_notas_texto(156792)

    assert texto == "Despesa de depreciação do período (26.581)"
    mock_http_get.assert_called_once_with(
        "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
        "?CodigoInstituicao=1&NumeroSequencialDocumento=156792",
        timeout=120,
    )


@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_sem_pdf_no_zip_retorna_none(mock_http_get):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apenas.xml", b"<xml/>")
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    assert fetch_notas_texto(999) is None


@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_erro_rede_retorna_none(mock_http_get):
    """Qualquer exceção (rede, ZIP corrompido, etc.) deve virar None, não crash."""
    mock_http_get.side_effect = Exception("timeout")

    assert fetch_notas_texto(156792) is None


@patch("ingest_notas_explicativas.pdfplumber.open")
@patch("ingest_notas_explicativas._http_get")
def test_fetch_notas_texto_remove_nul_bytes(mock_http_get, mock_pdf_open):
    """SQLite rejeita strings com NUL — mesma proteção de extract_pdf.py."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.pdf", b"%PDF-1.4")
    resp = MagicMock()
    resp.content = buf.getvalue()
    mock_http_get.return_value = resp

    page = MagicMock()
    page.extract_text.return_value = "texto\x00com\x00nul"
    mock_pdf_open.return_value.__enter__.return_value.pages = [page]

    texto = fetch_notas_texto(1)

    assert "\x00" not in texto
    assert texto == "textocomnul"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_notas_explicativas.py -k fetch_notas_texto -v`
Expected: `ImportError: cannot import name 'fetch_notas_texto'`

- [ ] **Step 3: Implementar `fetch_notas_texto`**

Adicione em `scripts/ingest/ingest_notas_explicativas.py`, logo após `extrair_pdf_do_pacote`:

```python
def fetch_notas_texto(numero_sequencial: int) -> str | None:
    """
    Baixa o pacote ZIP completo do documento (ITR/DFP) via NumeroSequencialDocumento
    e extrai o texto do PDF embutido — único lugar onde as notas explicativas
    existem (ver docstring do módulo).
    """
    url = DOWNLOAD_URL.format(numero=numero_sequencial)
    try:
        r = _http_get(url, timeout=120)
        pdf_bytes = extrair_pdf_do_pacote(r.content)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            return None
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        texto = "\n\n".join(p for p in pages if p.strip())
        return texto.replace("\x00", "")
    except Exception as e:
        print(f"    ERRO fetch (doc {numero_sequencial}): {e}")
        return None
```

- [ ] **Step 4: Rodar e confirmar que passam**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_notas_explicativas.py -k fetch_notas_texto -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest/ingest_notas_explicativas.py tests/test_ingest_notas_explicativas.py
git commit -m "feat: download + extração de PDF das notas explicativas"
```

---

### Task 5: Operações SQLite (upsert de candidatos, fila de pendentes, salvar resultado)

**Files:**
- Modify: `scripts/ingest/ingest_notas_explicativas.py`
- Modify: `tests/test_ingest_notas_explicativas.py`

- [ ] **Step 1: Escrever os testes (vão falhar — funções ainda não existem)**

Adicione a `tests/test_ingest_notas_explicativas.py`:

```python
# ── Operações SQLite ──────────────────────────────────────────────────────────

def _make_notas_conn():
    """In-memory SQLite com o schema mínimo de notas_explicativas (ver schema.sql)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE notas_explicativas (
            id                           INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj_companhia               TEXT NOT NULL,
            fonte                        TEXT NOT NULL CHECK (fonte IN ('ITR','DFP')),
            data_referencia              TEXT NOT NULL,
            versao                       INTEGER NOT NULL DEFAULT 1,
            numero_sequencial_documento  INTEGER NOT NULL,
            link_download                TEXT,
            texto_extraido               TEXT,
            extraido_em                  TEXT,
            extracao_falhou              INTEGER DEFAULT 0,
            chars_extraidos              INTEGER,
            created_at                   TEXT DEFAULT (datetime('now')),
            updated_at                   TEXT DEFAULT (datetime('now')),
            UNIQUE (cnpj_companhia, fonte, data_referencia)
        );
    """)
    return conn


def test_upsert_pendente_rows_insere_nova_linha():
    conn = _make_notas_conn()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    row = conn.execute(
        "SELECT versao, numero_sequencial_documento, texto_extraido FROM notas_explicativas"
    ).fetchone()
    assert row == (2, 156792, None)


def test_upsert_pendente_rows_versao_igual_preserva_texto():
    """Re-rodar o ingestor sem nova versão não deve apagar texto já extraído."""
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, versao, numero_sequencial_documento, texto_extraido) "
        "VALUES ('88.610.126/0001-29', 'ITR', '2026-03-31', 2, 156792, 'texto já extraído')"
    )
    conn.commit()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    texto = conn.execute("SELECT texto_extraido FROM notas_explicativas").fetchone()[0]
    assert texto == "texto já extraído"


def test_upsert_pendente_rows_versao_nova_reseta_texto():
    """Uma reapresentação (versão maior) invalida o texto extraído da versão antiga."""
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, versao, numero_sequencial_documento, "
        " texto_extraido, extracao_falhou) "
        "VALUES ('88.610.126/0001-29', 'ITR', '2026-03-31', 1, 156716, 'texto da v1', 1)"
    )
    conn.commit()
    rows = [{
        "cnpj_companhia": "88.610.126/0001-29", "fonte": "ITR",
        "data_referencia": "2026-03-31", "versao": 2,
        "numero_sequencial_documento": 156792,
    }]

    _upsert_pendente_rows(conn, rows)

    row = conn.execute(
        "SELECT versao, numero_sequencial_documento, texto_extraido, extracao_falhou "
        "FROM notas_explicativas"
    ).fetchone()
    assert row == (2, 156792, None, 0)


def test_fetch_pendentes_filtra_texto_nulo_e_fonte_ano():
    conn = _make_notas_conn()
    conn.executemany(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, numero_sequencial_documento, texto_extraido) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("88.610.126/0001-29", "ITR", "2026-03-31", 1, None),           # pendente
            ("88.610.126/0001-29", "ITR", "2026-06-30", 2, "já extraído"),  # não pendente
            ("88.610.126/0001-29", "DFP", "2026-12-31", 3, None),           # fonte errada
            ("00.000.000/0001-00", "ITR", "2026-03-31", 4, None),           # cnpj fora do filtro
        ],
    )
    conn.commit()

    docs = _fetch_pendentes(
        conn, {"88.610.126/0001-29"}, fonte="ITR", ano=2026, limite=10
    )

    assert len(docs) == 1
    assert docs[0]["numero_sequencial_documento"] == 1


def test_fetch_pendentes_retry_failed_so_pega_falhas():
    conn = _make_notas_conn()
    conn.executemany(
        "INSERT INTO notas_explicativas "
        "(cnpj_companhia, fonte, data_referencia, numero_sequencial_documento, "
        " texto_extraido, extracao_falhou) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("88.610.126/0001-29", "ITR", "2026-03-31", 1, None, 1),  # falhou antes
            ("88.610.126/0001-29", "ITR", "2026-06-30", 2, None, 0),  # nunca tentado
        ],
    )
    conn.commit()

    docs = _fetch_pendentes(
        conn, {"88.610.126/0001-29"}, fonte="ITR", ano=2026, limite=10, retry_failed=True
    )

    assert len(docs) == 1
    assert docs[0]["numero_sequencial_documento"] == 1


def test_salvar_sucesso_grava_texto_e_limpa_falha():
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(id, cnpj_companhia, fonte, data_referencia, numero_sequencial_documento, extracao_falhou) "
        "VALUES (1, '88.610.126/0001-29', 'ITR', '2026-03-31', 156792, 1)"
    )
    conn.commit()

    _salvar(conn, row_id=1, texto="texto extraído com sucesso")

    row = conn.execute(
        "SELECT texto_extraido, chars_extraidos, extracao_falhou FROM notas_explicativas WHERE id=1"
    ).fetchone()
    assert row == ("texto extraído com sucesso", len("texto extraído com sucesso"), 0)


def test_salvar_falha_marca_extracao_falhou():
    conn = _make_notas_conn()
    conn.execute(
        "INSERT INTO notas_explicativas "
        "(id, cnpj_companhia, fonte, data_referencia, numero_sequencial_documento) "
        "VALUES (1, '88.610.126/0001-29', 'ITR', '2026-03-31', 156792)"
    )
    conn.commit()

    _salvar(conn, row_id=1, texto=None)

    row = conn.execute(
        "SELECT texto_extraido, extracao_falhou FROM notas_explicativas WHERE id=1"
    ).fetchone()
    assert row == (None, 1)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_notas_explicativas.py -v`
Expected: `ImportError` para `_upsert_pendente_rows`, `_fetch_pendentes`, `_salvar`

- [ ] **Step 3: Implementar as 3 funções**

Adicione em `scripts/ingest/ingest_notas_explicativas.py`, após `fetch_notas_texto`:

```python
# ── Operações SQLite ──────────────────────────────────────────────────────────

def _upsert_pendente_rows(conn, rows: list[dict]) -> None:
    """
    Garante 1 linha por (cnpj, fonte, data_referencia) antes de extrair.
    Se a VERSAO subiu desde a última vez (reapresentação), reseta
    texto_extraido/extracao_falhou para forçar reprocessamento.
    """
    for row in rows:
        conn.execute(
            """
            INSERT INTO notas_explicativas
                (cnpj_companhia, fonte, data_referencia, versao, numero_sequencial_documento)
            VALUES (:cnpj_companhia, :fonte, :data_referencia, :versao, :numero_sequencial_documento)
            ON CONFLICT (cnpj_companhia, fonte, data_referencia) DO UPDATE SET
                versao = excluded.versao,
                numero_sequencial_documento = excluded.numero_sequencial_documento,
                texto_extraido = CASE WHEN excluded.versao > notas_explicativas.versao
                                       THEN NULL ELSE notas_explicativas.texto_extraido END,
                extracao_falhou = CASE WHEN excluded.versao > notas_explicativas.versao
                                        THEN 0 ELSE notas_explicativas.extracao_falhou END,
                updated_at = datetime('now')
            """,
            row,
        )
    conn.commit()


def _fetch_pendentes(conn, cnpjs: set, fonte: str, ano: int, limite: int,
                      retry_failed: bool = False) -> list[dict]:
    """Retorna documentos sem texto_extraido para as empresas/fonte/ano dados."""
    falhou_val = 1 if retry_failed else 0
    cnpj_list = list(cnpjs)
    if not cnpj_list:
        return []
    cnpj_ph = ",".join("?" * len(cnpj_list))
    sql = f"""
        SELECT id, cnpj_companhia, data_referencia, numero_sequencial_documento
        FROM notas_explicativas
        WHERE texto_extraido IS NULL
          AND extracao_falhou = ?
          AND fonte = ?
          AND data_referencia LIKE ?
          AND cnpj_companhia IN ({cnpj_ph})
        ORDER BY data_referencia DESC
        LIMIT ?
    """
    params = [falhou_val, fonte, f"{ano}-%", *cnpj_list, limite]
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _salvar(conn, row_id: int, texto: str | None) -> None:
    """Persiste texto extraído (ou marca falha) no banco SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    if texto:
        conn.execute(
            """
            UPDATE notas_explicativas
               SET texto_extraido = ?, chars_extraidos = ?, extraido_em = ?, extracao_falhou = 0
             WHERE id = ?
            """,
            (texto, len(texto), now, row_id),
        )
    else:
        conn.execute(
            "UPDATE notas_explicativas SET extracao_falhou = 1 WHERE id = ?", (row_id,)
        )
    conn.commit()
```

- [ ] **Step 4: Rodar e confirmar que passam**

Run: `cd scripts/ingest && python -m pytest ../../tests/test_ingest_notas_explicativas.py -v`
Expected: todos os testes passam (soma de Tasks 3+4+5: 16 testes)

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest/ingest_notas_explicativas.py tests/test_ingest_notas_explicativas.py
git commit -m "feat: operações SQLite do ingestor de notas explicativas"
```

---

### Task 6: `main()` + CLI + FTS + validação manual end-to-end

**Files:**
- Modify: `scripts/ingest/ingest_notas_explicativas.py`

- [ ] **Step 1: Implementar `_rebuild_fts` e `main()`**

Substitua o bloco `if __name__ == "__main__": pass` por:

```python
def _rebuild_fts(conn) -> None:
    """Reconstrói o índice FTS5 a partir do conteúdo atual de notas_explicativas."""
    print("Reconstruindo índice FTS5...")
    conn.execute("INSERT INTO notas_explicativas_fts(notas_explicativas_fts) VALUES ('rebuild')")
    conn.commit()
    print("  FTS5 reconstruído.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(cnpj_filter=None, ano=None, fonte="ITR", limite=20,
         retry_failed=False, rebuild_fts=False):
    conn = get_db()

    if rebuild_fts:
        _rebuild_fts(conn)
        return

    ano = ano or date.today().year
    cnpjs = {cnpj_filter} if cnpj_filter else watchlist_cnpjs()

    print(f"Baixando metadados {fonte} {ano}...")
    df_meta = fetch_doc_metadata(ano, fonte)
    candidatos = latest_por_periodo(df_meta, cnpjs, fonte)
    print(f"Períodos encontrados na watchlist: {len(candidatos)}")
    if candidatos:
        _upsert_pendente_rows(conn, candidatos)

    docs = _fetch_pendentes(conn, cnpjs, fonte, ano, limite, retry_failed)
    print(f"Pendentes para extração: {len(docs)}")

    ok = fail = 0
    for doc in docs:
        numero = doc["numero_sequencial_documento"]
        print(f"  [{doc['cnpj_companhia']}] {doc['data_referencia']} (doc {numero})...")
        texto = fetch_notas_texto(numero)
        time.sleep(0.5)  # respeita rate limit do portal CVM

        sucesso = bool(texto) and len(texto) > 100
        _salvar(conn, doc["id"], texto if sucesso else None)
        ok += 1 if sucesso else 0
        fail += 0 if sucesso else 1

    print(f"\nResultado: {ok} extraídos | {fail} falhas")
    if ok > 0:
        _rebuild_fts(conn)
        print("  Busca full-text disponível via notas_explicativas_fts.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Extrai o texto completo (com notas explicativas) de ITR/DFP da CVM."
    )
    p.add_argument("--cnpj",         help="Filtrar por CNPJ")
    p.add_argument("--ano",          type=int, help="Ano de referência (default: ano atual)")
    p.add_argument("--fonte",        choices=["ITR", "DFP"], default="ITR")
    p.add_argument("--limite",       type=int, default=20,
                   help="Máximo de documentos a processar nesta run (default: 20 — "
                        "cada PDF tem dezenas de MB, processar em lotes evita runs longas demais)")
    p.add_argument("--retry-failed", action="store_true",
                   help="Re-tentar docs marcados como falha")
    p.add_argument("--rebuild-fts",  action="store_true",
                   help="Apenas reconstrói o índice FTS5 sem baixar nada")
    args = p.parse_args()
    main(args.cnpj, args.ano, args.fonte, args.limite, args.retry_failed, args.rebuild_fts)
```

- [ ] **Step 2: Rodar a suíte completa de testes**

Run: `cd scripts/ingest && python -m pytest ../../tests/ -v`
Expected: todos os testes passam, nenhuma regressão.

- [ ] **Step 3: Validação manual end-to-end contra dado real conhecido**

Este é o teste de aceitação do plano inteiro: confirmar que o pipeline real
(sem mocks) reproduz os valores que já validamos manualmente na conversa
(Tangible=26,581 / Intangible=22,475 / Right-of-use=13,794 para a Frasle, 1T26).

```bash
cd scripts/ingest
source ../../.venv/bin/activate
python ingest_notas_explicativas.py --cnpj 88.610.126/0001-29 --ano 2026 --fonte ITR
```

Expected (stdout):
```
Baixando metadados ITR 2026...
Períodos encontrados na watchlist: 2
Pendentes para extração: 2
  [88.610.126/0001-29] 2026-03-31 (doc 156792)...
  [88.610.126/0001-29] 2026-06-30 (doc 160411)...
Resultado: 2 extraídos | 0 falhas

Reconstruindo índice FTS5...
  FTS5 reconstruído.
  Busca full-text disponível via notas_explicativas_fts.
```

Depois, confirme que o texto extraído bate com os valores já validados manualmente:

```bash
sqlite3 ../../cvm_research.db "
SELECT data_referencia, chars_extraidos FROM notas_explicativas
WHERE cnpj_companhia='88.610.126/0001-29' ORDER BY data_referencia;
"
sqlite3 ../../cvm_research.db "
SELECT texto_extraido FROM notas_explicativas
WHERE cnpj_companhia='88.610.126/0001-29' AND data_referencia='2026-03-31';
" | grep -A1 "Despesa de depreciação do período"
```

Expected: a linha da nota de Imobilizado deve conter `(26.581)` na coluna Consolidado, exatamente como no PDF que inspecionamos manualmente nesta conversa.

- [ ] **Step 4: Commit**

```bash
git add scripts/ingest/ingest_notas_explicativas.py
git commit -m "feat: CLI e main() do ingestor de notas explicativas"
```

---

### Task 7: Documentação

**Files:**
- Modify: `CLAUDE.md` (seção "Atualização manual dos dados")

- [ ] **Step 1: Adicionar o novo script à lista de ingestores**

Em `CLAUDE.md`, no bloco de comandos dentro de "Atualização manual dos dados", logo após a linha `python ingest_itr.py         # demonstrativo trimestral (ano corrente)`, adicione:

```
python ingest_notas_explicativas.py --ano <ANO> --fonte ITR   # texto completo (com notas) do ITR
python ingest_notas_explicativas.py --ano <ANO> --fonte DFP   # texto completo (com notas) do DFP anual
```

E no bloco de "Histórico completo", após a linha do `ingest_vlmo.py --desde 2018`, adicione uma nota (não um backfill automático — ver justificativa abaixo):

```
# Notas explicativas: sem --historico por padrão — cada PDF tem dezenas de MB
# e centenas de empresas × anos vira um volume grande. Rodar sob demanda por
# empresa/ano quando precisar de um dado que só existe em nota (ex: quebra de
# depreciação por classe de ativo), como em:
#   python ingest_notas_explicativas.py --cnpj <CNPJ> --ano <ANO> --fonte ITR
```

Adicione também uma nova subseção em "Tabelas e campos principais", após a seção de `demonstrativos_contabeis`:

```markdown
### `notas_explicativas` — texto completo do ITR/DFP (com notas explicativas)
`cnpj_companhia, fonte ('ITR'/'DFP'), data_referencia, versao,`
`numero_sequencial_documento, texto_extraido (NULL = não extraído), chars_extraidos`

Diferença para `demonstrativos_contabeis`: aquela tabela só tem os quadros
padronizados (BPA/BPP/DRE/DFC_MI/DVA); esta tem o **PDF completo do documento**,
incluindo notas explicativas (movimentação de Imobilizado/Intangível/Direito de
Uso, provisões, etc.) — dado que não existe em nenhum feed estruturado da CVM.
Populada sob demanda via `ingest_notas_explicativas.py` (não faz parte do fluxo
semanal automático — ver script para detalhes). Busca full-text via
`notas_explicativas_fts` (mesmo padrão de `ipe_docs_fts`).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: documenta ingest_notas_explicativas.py"
```

---

## Self-Review

**Spec coverage:**
- "Tem essa informação no XBRL?" → respondido e confirmado por inspeção manual (Task 3 docstring + descoberta já registrada na conversa): não, o XML do pacote é só os quadros já normalizados.
- "É trabalho de webscraping?" → não: é 1 HTTP GET documentado por filing, usando um ID (`ID_DOC`) que a própria CVM já publica no CSV aberto. Coberto pela Task 2 (`fetch_doc_metadata`) e Task 4 (`fetch_notas_texto`).
- "Esboço do que precisa ser alterado para implementação" → Tasks 1-6 cobrem schema, utils, novo script completo.
- "Teste" → cada task tem testes TDD (puros/mockados) + Task 6 tem uma validação manual end-to-end contra o dado real já conhecido (Frasle 1T26).
- "Execução" → Task 6 Step 3 dá o comando exato e o output esperado; Task 7 documenta como rodar no dia a dia.

**Placeholder scan:** nenhum "TODO"/"implementar depois" — todo código é completo e executável como está.

**Type consistency:** `latest_por_periodo(df_meta, cnpjs, fonte)` usado de forma consistente nas Tasks 3 e 6; `_fetch_pendentes(conn, cnpjs, fonte, ano, limite, retry_failed)` e `_salvar(conn, row_id, texto)` consistentes entre Tasks 5 e 6 (main usa `doc["id"]`, que é exatamente a coluna que `_fetch_pendentes` seleciona).

---

## Notas de escopo (fora deste plano)

- **Parsing estruturado das notas** (extrair automaticamente "Despesa de depreciação do período" por nota em linhas de uma tabela, tipo `demonstrativos_contabeis`) fica fora de escopo — este plano só resolve a extração de **texto**, pesquisável via FTS5, igual ao que já existe para `ipe_docs`. Ler valores específicos de uma nota continua sendo um passo manual (grep/leitura), como fizemos com a Frasle nesta conversa.
- **Backfill histórico completo** (todas as ~111 empresas da watchlist × todos os anos) não está incluído por padrão — ver nota da Task 7. Cada PDF tem dezenas de MB; rodar para todo o histórico de todas as empresas de uma vez pode levar horas e consumir bastante disco/banda. Recomenda-se rodar sob demanda (por CNPJ) quando uma pesquisa específica precisar de um dado de nota, e considerar um backfill dirigido (ex: só as empresas mais pesquisadas) como um plano separado se isso virar necessidade recorrente.
