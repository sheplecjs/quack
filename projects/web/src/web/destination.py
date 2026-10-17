"""The project's DuckDB destination, shared by every source's pipeline."""

import os
from pathlib import Path

import dlt

DEFAULT_DUCKDB_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "web" / "data.duckdb"
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
