"""The `web-load` CLI: one subcommand per source, each loading into the project's DuckDB database."""

import argparse
from collections.abc import Sequence

from web.ingestion.shynet import pipeline as shynet
from web.ingestion.shynet_db import pipeline as shynet_db

# Each source module registers its own subcommand
SOURCES = (shynet, shynet_db)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Load raw web analytics data into DuckDB."
    )
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
