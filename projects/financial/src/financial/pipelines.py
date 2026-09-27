"""Pipelines that load raw financial data into the project's DuckDB database."""

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

import dlt
from dlt.common.pipeline import LoadInfo

from financial.sources import alpha_vantage_source

DEFAULT_DUCKDB_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "financial" / "data.duckdb"
)


def duckdb_path() -> Path:
    return Path(os.environ.get("DUCKDB_PATH", DEFAULT_DUCKDB_PATH))


def create_pipeline(pipeline_name: str, dataset_name: str) -> dlt.Pipeline:
    """A pipeline that writes `dataset_name` as a schema in the project's DuckDB file."""
    path = duckdb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=dlt.destinations.duckdb(str(path)),
        dataset_name=dataset_name,
    )


def load_alpha_vantage(
    symbols: Sequence[str] | None = None,
    resources: Sequence[str] | None = None,
) -> LoadInfo:
    """Load Alpha Vantage data into the `alpha_vantage` schema.

    `symbols` overrides the list in .dlt/config.toml; `resources` limits the
    run to a subset of the source's resources to save API quota.
    """
    source = (
        alpha_vantage_source(symbols=list(symbols))
        if symbols
        else alpha_vantage_source()
    )
    if resources:
        source = source.with_resources(*resources)

    pipeline = create_pipeline("alpha_vantage", dataset_name="alpha_vantage")
    return pipeline.run(source)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Alpha Vantage data into DuckDB.")
    parser.add_argument(
        "--symbols", nargs="+", help="Ticker symbols (default: from config.toml)"
    )
    parser.add_argument(
        "--resources",
        nargs="+",
        choices=["daily_prices", "company_overviews", "economic_indicators"],
        help="Only load these resources (default: all)",
    )
    args = parser.parse_args()

    print(load_alpha_vantage(symbols=args.symbols, resources=args.resources))


if __name__ == "__main__":
    main()
