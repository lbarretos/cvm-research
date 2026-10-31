"""Stress test da Etapa 8: extração de garantias (extrai_rf.py) medida contra a espécie do SND, sem leitura humana.

Gabarito: `rf_ativos.especie_garantia` (SND) da debênture cuja escritura está no IPE das empresas da base. A escritura
é ligada à emissão pela capa (mesma regra do ingest_rf_docs: "14ª emissão", "décima sexta emissão"). Só escrituras
originais (aditamento repete ou altera, e confunde a medida). Somente leitura.

Mede, por escritura:
- garantia real (alienação/cessão fiduciária, penhor, hipoteca) achada × SND 'Real'  → recall e falso positivo;
- espécie declarada na capa ("da espécie quirografária") × SND;
- fiança/aval não têm gabarito no SND: só contados.

    python st8_medir_extracao.py [--mostrar-erros N]
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "scripts" / "ingest"))

import extrai_rf  # noqa: E402
import ingest_rf_docs  # noqa: E402
import rf_fontes as F  # noqa: E402

REAIS = {"alienacao_fiduciaria", "cessao_fiduciaria", "penhor", "hipoteca"}
ESPECIE_CAPA = re.compile(r"especie\s+(?:com\s+)?(quirografaria|subordinada|garantia real|real|garantia flutuante|flutuante)")


def especie_da_capa(texto: str) -> str | None:
    m = ESPECIE_CAPA.search(F.norm(texto[:3000]))
    if not m:
        return None
    e = m.group(1)
    return {"quirografaria": "Quirografária", "subordinada": "Subordinada", "garantia real": "Real", "real": "Real",
            "garantia flutuante": "Flutuante", "flutuante": "Flutuante"}[e]


def casos(conn):
    """(escritura, especie SND) para cada escritura original ligada a uma única emissão do SND."""
    debs: dict[str, list[dict]] = {}
    for cnpj, emissao, especie in conn.execute(
            "SELECT DISTINCT emissor_cnpj, emissao, especie_garantia FROM rf_ativos "
            "WHERE tipo = 'DEB' AND fonte = 'snd' AND emissao IS NOT NULL"):
        debs.setdefault(cnpj, []).append({"tipo": "DEB", "emissao": emissao, "especie": especie})
    for prot, cnpj, assunto, texto in conn.execute(
            "SELECT protocolo_entrega, cnpj_companhia, assunto, texto_extraido FROM ipe_docs "
            "WHERE categoria LIKE 'Escrituras%' AND texto_extraido IS NOT NULL"):
        if re.search(r"aditamento", F.norm((assunto or "") + " " + texto[:400])):
            continue
        achados = {(d["emissao"], d["especie"]) for d in debs.get(cnpj, [])
                   if ingest_rf_docs._abertura_cita_emissao(texto, d)}
        especies = {e for _, e in achados}
        if len({int(re.sub(r"\D", "", n) or 0) for n, _ in achados}) == 1 and len(especies) == 1:
            yield prot, especies.pop(), texto


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mostrar-erros", type=int, default=5)
    a = p.parse_args()
    conn = sqlite3.connect(f"file:{RAIZ / 'cvm_research.db'}?mode=ro", uri=True)
    n = Counter()
    erros = {"fn_real": [], "fp_real": [], "especie": []}
    for prot, especie_snd, texto in casos(conn):
        tipos = {g["tipo"] for g in extrai_rf.extrair(texto, "DEB")["garantias"] if g["escopo"] == "titulo"}
        real = bool(tipos & REAIS)
        n["docs"] += 1
        n[f"snd_{especie_snd}"] += 1
        if especie_snd == "Real":
            n["real_ok" if real else "real_fn"] += 1
            if not real:
                erros["fn_real"].append(prot)
        else:
            n["nao_real_fp" if real else "nao_real_ok"] += 1
            if real:
                erros["fp_real"].append((prot, especie_snd, sorted(tipos & REAIS)))
                # quirografária "com garantia adicional real": o SND diz Quirografária, mas a garantia real existe
                n["fp_explicado_capa"] += bool(re.search(r"garantia adicional real|com garantia real",
                                                         F.norm(texto[:4000])))
        capa = especie_da_capa(texto)
        n["capa_achada"] += capa is not None
        if capa:
            n["capa_ok" if capa == especie_snd else "capa_erro"] += 1
            if capa != especie_snd:
                erros["especie"].append((prot, capa, especie_snd))
        n["fidejussoria"] += bool(tipos & {"fianca", "aval"})

    def pct(x, y):
        return f"{x}/{y} ({100 * x / y:.0f}%)" if y else "–"
    print(f"escrituras originais ligadas a uma emissão do SND: {n['docs']}")
    print("  SND: " + ", ".join(f"{k[4:]} {v}" for k, v in sorted(n.items()) if k.startswith("snd_")))
    print(f"garantia real, recall (SND Real):            {pct(n['real_ok'], n['real_ok'] + n['real_fn'])}")
    print(f"garantia real, falso positivo (SND não Real): {pct(n['nao_real_fp'], n['nao_real_fp'] + n['nao_real_ok'])}")
    print(f"  dos quais a capa diz 'garantia adicional real': {n['fp_explicado_capa']}")
    print(f"espécie na capa achada:                       {pct(n['capa_achada'], n['docs'])}")
    print(f"espécie na capa = SND:                        {pct(n['capa_ok'], n['capa_achada'])}")
    print(f"com fiança/aval (sem gabarito):               {n['fidejussoria']}")
    for k, v in erros.items():
        if v:
            print(f"\n-- {k} ({len(v)}), primeiros {a.mostrar_erros}:")
            for e in v[:a.mostrar_erros]:
                print("  ", e)


if __name__ == "__main__":
    main()
