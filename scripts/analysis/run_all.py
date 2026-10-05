"""
Orquestrador das camadas de consistência (scripts/analysis/).

  python run_all.py --layer 2 --cnpj 84.429.695/0001-11
  python run_all.py --layer 1,2 --cnpj 84.429.695/0001-11
  python run_all.py --layer 2 --full

Os demais argumentos (--cnpj, --tipo-doc, --desde, --ate, --full, --tol-abs,
--tol-rel) são repassados ao script de cada camada. Camadas: 1 soma
hierárquica, 2 cruzamento entre filings, 3 granularidade, 5 trilha temporal
(a Camada 4, similaridade, está dentro dela), 6 desacúmulo. update_weekly.sh
chama `run_all.py --layer N --full` para N = 1, 2, 3, 5, 6 logo após
ingest_dfp/ingest_itr (a 6 depende dos resumos da 2).
"""
import argparse

import check_cross_period
import check_granularity
import check_hierarchy_sums
import check_text_stability
import derive_quarters
from consistency_utils import get_db
from filings import rebuild_filings  # consistency_utils põe scripts/ingest no sys.path

LAYERS = {
    1: check_hierarchy_sums.main,
    2: check_cross_period.main,
    3: check_granularity.main,
    5: check_text_stability.main,
    6: derive_quarters.main,
}


def main(argv=None) -> list[str]:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layer", required=True,
                        help="Camadas a rodar, separadas por vírgula (disponíveis: "
                             + ",".join(str(k) for k in sorted(LAYERS)) + ")")
    args, resto = parser.parse_known_args(argv)
    layers = [int(x) for x in args.layer.split(",")]
    desconhecidas = [l for l in layers if l not in LAYERS]
    if desconhecidas:
        parser.error(f"camada(s) não implementada(s): {desconhecidas}")
    # as views de DRE/balanço leem `filings`; reconstruir aqui cobre dados ingeridos por fora dos ingestores
    conn = get_db()
    print(f"filings: {rebuild_filings(conn)} linhas")
    conn.close()
    run_ids = []
    for layer in layers:
        print(f"\n═══ Camada {layer} ═══")
        run_ids.append(LAYERS[layer](resto))
    return run_ids


if __name__ == "__main__":
    main()
