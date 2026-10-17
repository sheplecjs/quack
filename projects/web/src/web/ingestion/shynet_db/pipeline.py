"""Load Shynet's sessions and hits into the `shynet_db` schema, and its `web-load` subcommand."""

import argparse
from collections.abc import Sequence

from dlt.common.pipeline import LoadInfo

from web.destination import create_pipeline
from web.ingestion.shynet_db.source import TABLES, shynet_db_source

RESOURCES = tuple(name for name, _, _ in TABLES.values())


def load_shynet_db(
    resources: Sequence[str] | None = None, refresh: bool = False
) -> LoadInfo:
    """Load Shynet's sessions and hits into the `shynet_db` schema.

    Each run reads the rows seen since the last load. `resources` limits the run to a subset of
    the tables; `refresh` drops the selected tables and their state first, so they reload in full.
    """
    source = shynet_db_source()
    if resources:
        source = source.with_resources(*resources)

    pipeline = create_pipeline("shynet_db", dataset_name="shynet_db")
    if refresh:
        return pipeline.run(source, refresh="drop_resources")
    return pipeline.run(source)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `shynet-db` subcommand."""
    parser = subparsers.add_parser(
        "shynet-db", help="Load Shynet sessions and hits from its Postgres database"
    )
    parser.add_argument(
        "--resources",
        nargs="+",
        choices=RESOURCES,
        help="Only load these tables (default: all)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Drop the selected tables and state before loading",
    )
    parser.set_defaults(
        load=lambda args: load_shynet_db(resources=args.resources, refresh=args.refresh)
    )
