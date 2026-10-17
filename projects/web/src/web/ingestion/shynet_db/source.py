"""dlt source reading sessions and hits straight from a Shynet instance's Postgres database.

Models: https://github.com/milesmcc/shynet/blob/master/shynet/analytics/models.py

Unlike the dashboard API, this gives one row per session and per hit, which session-level analysis
(e.g. bot classification) needs. It connects as a read-only role that can see only the columns
listed below: the role has no access to `ip`, `latitude`, `longitude` or `identifier`, nor to any
other table, so every query names its columns.

Both tables are updated after a row is first written: a session's last_seen and is_bounce change with
each hit, and a hit's last_seen and heartbeats change while its page stays open. Each table is
therefore read incrementally on last_seen (with a lag, for rows committed late) and upserted on its
primary key. Rows deleted in Shynet stay in the destination.
"""

from typing import Any

import dlt
from dlt.sources import DltResource
from dlt.sources.sql_database import sql_table

from web.ingestion.shynet_db.config import ShynetDbConfig

UPSERT: Any = {"disposition": "merge", "strategy": "upsert"}

# Shynet table -> (destination table, primary key, columns the read-only role may select)
TABLES = {
    "analytics_session": (
        "sessions",
        "uuid",
        (
            "uuid",
            "service_id",
            "start_time",
            "last_seen",
            "user_agent",
            "browser",
            "device",
            "device_type",
            "os",
            "asn",
            "country",
            "time_zone",
            "is_bounce",
        ),
    ),
    "analytics_hit": (
        "hits",
        "id",
        (
            "id",
            "session_id",
            "service_id",
            "initial",
            "start_time",
            "last_seen",
            "heartbeats",
            "tracker",
            "location",
            "referrer",
            "load_time",
        ),
    ),
}


def shynet_tables(credentials: str, lag_seconds: float) -> list[DltResource]:
    """One upserted, incremental resource per Shynet table. Takes any SQLAlchemy URL, so tests can use SQLite."""
    resources = []
    for table, (name, primary_key, columns) in TABLES.items():
        resource = sql_table(
            credentials=credentials,
            table=table,
            schema="public" if credentials.startswith("postgresql") else None,
            included_columns=list(columns),
            incremental=dlt.sources.incremental("last_seen", lag=lag_seconds),
            # Reflect on first extract, not when the source is built
            defer_table_reflect=True,
            write_disposition=UPSERT,
            primary_key=primary_key,
        )
        resources.append(resource.with_name(name))
    return resources


@dlt.source(name="shynet_db")
def shynet_db_source(
    credentials: str = dlt.secrets.value, lag_seconds: float | None = None
) -> list[DltResource]:
    """Shynet's sessions and hits, read from its Postgres database.

    dlt reads `credentials` from `[sources.shynet_db]` in .dlt/secrets.toml (or
    SOURCES__SHYNET_DB__CREDENTIALS). ShynetDbConfig validates it, including that it requires TLS,
    before any connection is made.
    """
    raw: dict[str, Any] = {"credentials": credentials}
    if lag_seconds is not None:
        raw["lag_seconds"] = lag_seconds
    settings = ShynetDbConfig.model_validate(raw)
    return shynet_tables(settings.credentials.get_secret_value(), settings.lag_seconds)
