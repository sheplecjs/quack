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
    names = list(subparsers.choices)
    subparsers.add_parser(
        "all", help="Load every source in turn, each with its default options"
    ).set_defaults(load=None)
    args = parser.parse_args(argv)

    if args.load is not None:
        print(args.load(args))
        return
    # Stops at the first source that fails
    for name in names:
        source_args = parser.parse_args([name])
        print(f"{name}: {source_args.load(source_args)}")


if __name__ == "__main__":
    main()
