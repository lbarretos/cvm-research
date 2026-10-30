"""Stress test da Etapa 8: extração por regra (scripts/ingest/extrai_rf.py) em termos e escrituras reais.

Lê PDFs locais (baixados da aba de documentos do título no data.anbima.com.br, do RAD ou do Fundos.NET), roda a
extração e imprime partes, garantias (com escopo) e lastro, com o trecho de evidência. Não toca no banco. Serve
para medir a regra em mais documentos e anotar acertos e erros em 08-renda-fixa.md.

    python st8_extrai_rf.py CRA termo1.pdf termo2.pdf
    python st8_extrai_rf.py DEB escritura.pdf
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "ingest"))

import extrai_rf  # noqa: E402
from extract_pdf import pdf_bytes_text  # noqa: E402

if len(sys.argv) < 3 or sys.argv[1] not in ("DEB", "CRI", "CRA"):
    sys.exit(__doc__)
tipo = sys.argv[1]
for arquivo in sys.argv[2:]:
    texto = pdf_bytes_text(Path(arquivo).read_bytes())
    if not texto:
        print(f"\n== {arquivo}: não é PDF ou não tem texto (digitalizado?)")
        continue
    limpo = extrai_rf._limpo(texto)
    corte = len(extrai_rf._sem_anexo_de_terceiros(limpo)) / len(limpo)
    r = extrai_rf.extrair(texto, tipo)
    print(f"\n== {arquivo}: {len(texto):,} caracteres; anexo de terceiros cortado: "
          + (f"sim, em {corte:.0%} do texto" if corte < 1 else "não"))
    print("-- partes")
    for p in r["partes"]:
        print(f"   {p['papel']:<18} {p['cnpj']}  {p['nome']}")
    print("-- garantias")
    for g in r["garantias"]:
        print(f"   {g['tipo']:<20} {g['escopo']:<7} {g['descricao']}\n      … {g['evidencia'][:220]}")
    print("-- lastro")
    for l in r["lastro"]:
        print(f"   {l['tipo_lastro']:<15} … {l['evidencia'][:200]}")
