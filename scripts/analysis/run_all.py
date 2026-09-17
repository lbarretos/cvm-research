"""
Orquestrador das camadas de consistência (scripts/analysis/).

  python run_all.py --layer 2 --cnpj 84.429.695/0001-11
  python run_all.py --layer 2 --full

Os demais argumentos (--cnpj, --tipo-doc, --desde, --ate, --full, --tol-abs,
--tol-rel) são repassados ao script de cada camada. Camadas disponíveis
crescem a cada fase do plano (1 = soma hierárquica, 3 = granularidade,
5 = trilha temporal, 6 = desacúmulo). Não entra em update_weekly.sh.
"""
import argparse

import check_cross_period

LAYERS = {
    2: check_cross_period.main,
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
    run_ids = []
    for layer in layers:
        print(f"\n═══ Camada {layer} ═══")
        run_ids.append(LAYERS[layer](resto))
    return run_ids


if __name__ == "__main__":
    main()
