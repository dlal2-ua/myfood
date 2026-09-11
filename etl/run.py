"""CLI del ETL (documento 2, sección 11.1).

Uso:
    python -m etl.run --source usda_foundation
    python -m etl.run --source usda_sr
"""

from __future__ import annotations

import argparse
import sys

from etl.sources import ciqual, off, usda

_USDA_SOURCES = ("usda_foundation", "usda_sr")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ETL de datos nutricionales de MyFood")
    parser.add_argument(
        "--source",
        required=True,
        choices=[*_USDA_SOURCES, "bedca", "ciqual", "off", "off_brands"],
    )
    parser.add_argument("--country", default=None, help="Solo aplica a --source off")
    args = parser.parse_args(argv)

    if args.source in _USDA_SOURCES:
        result = usda.load(args.source)
        print(
            f"[{args.source}] leídos={result.stats.read} "
            f"cargados={result.stats.upserted} descartados={result.stats.rejected}"
        )
        if result.rejected_path:
            print(f"  descartes registrados en {result.rejected_path}")
        return 0

    if args.source == "ciqual":
        result = ciqual.load()
        print(
            f"[ciqual] leídos={result.stats.read} "
            f"cargados={result.stats.upserted} descartados={result.stats.rejected}"
        )
        if result.rejected_path:
            print(f"  descartes registrados en {result.rejected_path}")
        return 0

    if args.source == "off":
        result = off.load()
        print(
            f"[off] leídos={result.stats.read} "
            f"cargados={result.stats.upserted} descartados={result.stats.rejected}"
        )
        if result.rejected_path:
            print(f"  descartes registrados en {result.rejected_path}")
        return 0

    if args.source == "off_brands":
        result = off.load_by_brand()
        print(
            f"[off_brands] leídos={result.stats.read} "
            f"cargados={result.stats.upserted} descartados={result.stats.rejected}"
        )
        if result.rejected_path:
            print(f"  descartes registrados en {result.rejected_path}")
        return 0

    print(f"Fuente '{args.source}' todavía no implementada.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
