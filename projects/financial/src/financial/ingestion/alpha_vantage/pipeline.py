"""Load Alpha Vantage data into the `alpha_vantage` schema, and its `financial-load` subcommand."""

import argparse
from collections.abc import Sequence

from dlt.common.pipeline import LoadInfo

from financial.destination import create_pipeline
from financial.ingestion.alpha_vantage.source import alpha_vantage_source

RESOURCES = ("daily_prices", "company_overviews", "economic_indicators")


def load_alpha_vantage(
    symbols: Sequence[str] | None = None,
    resources: Sequence[str] | None = None,
    refresh: bool = False,
) -> LoadInfo:
    """Load Alpha Vantage data into the `alpha_vantage` schema.

    `symbols` overrides the list in .dlt/config.toml; `resources` limits the
    run to a subset of the source's resources to save API quota. `refresh` drops
    the selected resources' tables and state first, e.g. after a write-disposition change.
    """
    source = (
        alpha_vantage_source(symbols=list(symbols))
        if symbols
        else alpha_vantage_source()
    )
    if resources:
        source = source.with_resources(*resources)

    pipeline = create_pipeline("alpha_vantage", dataset_name="alpha_vantage")
    if refresh:
        return pipeline.run(source, refresh="drop_resources")
    return pipeline.run(source)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `alpha-vantage` subcommand."""
    parser = subparsers.add_parser(
        "alpha-vantage", help="Load Alpha Vantage prices, fundamentals and indicators"
    )
    parser.add_argument(
        "--symbols", nargs="+", help="Ticker symbols (default: from config.toml)"
    )
    parser.add_argument(
        "--resources",
        nargs="+",
        choices=RESOURCES,
        help="Only load these resources (default: all)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Drop the selected resources' tables and state before loading",
    )
    parser.set_defaults(
        load=lambda args: load_alpha_vantage(
            symbols=args.symbols, resources=args.resources, refresh=args.refresh
        )
    )
