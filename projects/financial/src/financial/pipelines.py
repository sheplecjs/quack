"""The `financial-load` CLI: one subcommand per source, each loading into the project's DuckDB database."""

import argparse
from collections.abc import Sequence

from financial.ingestion.alpha_vantage import pipeline as alpha_vantage

# Each source module registers its own subcommand
SOURCES = (alpha_vantage,)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load raw financial data into DuckDB.")
    subparsers = parser.add_subparsers(title="sources", required=True)
    for source in SOURCES:
        source.add_parser(subparsers)
    args = parser.parse_args(argv)

    print(args.load(args))


if __name__ == "__main__":
    main()
