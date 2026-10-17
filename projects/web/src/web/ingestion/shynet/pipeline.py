"""Load Shynet data into the `shynet` schema, and its `web-load` subcommand."""

import argparse
from collections.abc import Sequence
from datetime import date

from dlt.common.pipeline import LoadInfo

from web.destination import create_pipeline
from web.ingestion.shynet.source import BREAKDOWNS, shynet_source

RESOURCES = (
    "services",
    "daily_stats",
    "hourly_stats",
    *(f"daily_{key}" for key in BREAKDOWNS),
)


def load_shynet(
    start_date: date | None = None,
    end_date: date | None = None,
    resources: Sequence[str] | None = None,
    refresh: bool = False,
) -> LoadInfo:
    """Load Shynet stats into the `shynet` schema.

    `start_date` / `end_date` load an explicit window, e.g. a backfill, instead of resuming from the
    last day loaded. `resources` limits the run to a subset of the source's resources. `refresh` drops
    the selected resources' tables and state first, so they reload from initial_start_date.
    """
    source = shynet_source(
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )
    if resources:
        source = source.with_resources(*resources)

    pipeline = create_pipeline("shynet", dataset_name="shynet")
    if refresh:
        return pipeline.run(source, refresh="drop_resources")
    return pipeline.run(source)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `shynet` subcommand."""
    parser = subparsers.add_parser("shynet", help="Load Shynet traffic stats")
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        help="First day to load, YYYY-MM-DD (default: resume from the last day loaded)",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="Last day to load, YYYY-MM-DD (default: today, UTC)",
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
        load=lambda args: load_shynet(
            start_date=args.start_date,
            end_date=args.end_date,
            resources=args.resources,
            refresh=args.refresh,
        )
    )
