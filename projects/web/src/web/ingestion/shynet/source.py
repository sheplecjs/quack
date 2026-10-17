"""dlt source for the dashboard API of a Shynet web analytics instance.

Docs: https://github.com/milesmcc/shynet/blob/master/GUIDE.md#api

The API serves the dashboard's aggregates, not raw sessions or hits: for every service the token can
see, `Service.get_core_stats()` over a date range. The source requests one day at a time, so each table
is at the grain of a service and a day. The exception is `hourly_stats`, which comes from the dashboard
chart (Shynet makes it hourly for ranges under three days). Days are calendar days in the time zone of
the Shynet server (its TIME_ZONE setting).

Each day's response is fetched once and shared by every resource that needs it. The response's
`currently_online` and `has_hits` aren't scoped to the date range, and `compare` repeats the previous
period, so none of them is loaded.
"""

import functools
import re
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

import dlt
from dlt.common.schema.typing import TDataType, TTableSchemaColumns
from dlt.sources import DltResource
from dlt.sources.helpers.requests import Client, RequestException

from web.ingestion.shynet.config import ShynetConfig, today

type Fetch = Callable[[date], list[dict[str, Any]]]

UPSERT: Any = {"disposition": "merge", "strategy": "upsert"}

# Stats key in the response -> the field each of its rows is grouped by. Shynet keeps the top 300
# rows of each, ordered by count. Pages and referrers count hits (referrers only each session's
# initial hit); the rest count sessions.
BREAKDOWNS = {
    "locations": "location",
    "referrers": "referrer",
    "countries": "country",
    "operating_systems": "os",
    "browsers": "browser",
    "devices": "device",
    "device_types": "device_type",
}

# Django's JSON encoder writes timedeltas as ISO 8601 durations (duration_iso_string)
DURATION_PATTERN = re.compile(
    r"^(?P<sign>-?)P(?P<days>\d+)DT(?P<hours>\d+)H(?P<minutes>\d+)M(?P<seconds>\d+(?:\.\d+)?)S$"
)

_client = Client(raise_for_status=False)


class ShynetError(Exception):
    """Raised when the Shynet API rejects a request or returns something unexpected."""


def _get(settings: ShynetConfig, params: dict[str, str]) -> dict[str, Any]:
    try:
        response = _client.get(
            settings.endpoint,
            params=params,
            headers={"Authorization": f"Token {settings.api_key.get_secret_value()}"},
        )
    except RequestException as e:
        raise ShynetError(f"dashboard {params}: {type(e).__name__}") from None
    # A missing or unknown token gets an empty 403
    if response.status_code == 403:
        raise ShynetError("Shynet rejected the API token (HTTP 403)")
    if not response.ok:
        raise ShynetError(
            f"dashboard {params}: HTTP {response.status_code} {response.text[:200]}"
        )
    # A proxy, login page or wrong path can answer 200 with something else entirely
    hint = f"expected Shynet's dashboard JSON from {settings.endpoint}; check base_url"
    try:
        payload = response.json()
    except ValueError:
        content_type = response.headers.get("Content-Type", "no content type")
        raise ShynetError(f"{hint} (got {content_type})") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), list):
        raise ShynetError(f"{hint} (the response has no list of services)")
    return payload


def _dashboard(settings: ShynetConfig, day: date) -> list[dict[str, Any]]:
    """The requested services' stats for one day: all the token can see, or each of service_uuids."""
    params = {"startDate": day.isoformat(), "endDate": day.isoformat()}
    if not settings.service_uuids:
        return _get(settings, params)["services"]

    services = []
    for uuid in settings.service_uuids:
        found = _get(settings, {**params, "uuid": str(uuid)})["services"]
        if not found:
            raise ShynetError(
                f"service {uuid} doesn't exist or isn't shared with this token"
            )
        services.extend(found)
    return services


def _days(settings: ShynetConfig) -> list[date]:
    """The days for this resource to load, recording the last one in its state.

    An explicit start_date / end_date wins. Otherwise a run starts lookback_days before the last day
    loaded (or at initial_start_date on the first run) and ends today, so partial days are completed
    by later runs. dlt commits the state only with a successful load.
    """
    state = dlt.current.resource_state()
    end = settings.end_date or today()
    last = date.fromisoformat(state["last_date"]) if "last_date" in state else None
    if settings.start_date:
        start = settings.start_date
    elif last:
        start = max(
            settings.initial_start_date, last - timedelta(days=settings.lookback_days)
        )
    else:
        start = settings.initial_start_date
    # A backfill of older days mustn't move the next run's start back
    state["last_date"] = max(end, last or end).isoformat()
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def _duration_seconds(value: str | float | None) -> float | None:
    """Seconds in an ISO 8601 duration, e.g. P0DT00H05M12.345678S.

    Shynet falls back to float seconds on databases without duration arithmetic.
    """
    if value is None or isinstance(value, int | float):
        return value
    match = DURATION_PATTERN.match(value)
    if not match:
        raise ShynetError(f"unexpected duration {value!r}")
    seconds = timedelta(
        days=int(match["days"]),
        hours=int(match["hours"]),
        minutes=int(match["minutes"]),
        seconds=float(match["seconds"]),
    ).total_seconds()
    return -seconds if match["sign"] else seconds


def _columns(**data_types: TDataType) -> TTableSchemaColumns:
    # Declared up front: nullable columns would otherwise be missing until a non-null value arrives
    return {name: {"data_type": data_type} for name, data_type in data_types.items()}


@dlt.resource(
    name="services",
    write_disposition=UPSERT,
    primary_key="uuid",
    columns=_columns(uuid="text", name="text", link="text"),
)
def services(settings: ShynetConfig, fetch: Fetch) -> Iterator[list[dict[str, Any]]]:
    """The services loaded, as of the last day of the run."""
    yield [
        {"uuid": service["uuid"], "name": service["name"], "link": service["link"]}
        for service in fetch(settings.end_date or today())
    ]


@dlt.resource(
    name="daily_stats",
    write_disposition=UPSERT,
    primary_key=("service_uuid", "date"),
    columns=_columns(
        service_uuid="text",
        date="date",
        session_count="bigint",
        hit_count="bigint",
        bounce_rate_pct="double",
        avg_session_duration="double",
        avg_load_time="double",
        avg_hits_per_session="double",
    ),
)
def daily_stats(settings: ShynetConfig, fetch: Fetch) -> Iterator[list[dict[str, Any]]]:
    """Core stats per service per day. Averages and the bounce rate are null on days without sessions."""
    for day in _days(settings):
        yield [_daily_row(service, day) for service in fetch(day)]


def _daily_row(service: dict[str, Any], day: date) -> dict[str, Any]:
    stats = service["stats"]
    return {
        "service_uuid": service["uuid"],
        "date": day,
        "session_count": stats["session_count"],
        "hit_count": stats["hit_count"],
        "bounce_rate_pct": stats["bounce_rate_pct"],
        "avg_session_duration": _duration_seconds(stats["avg_session_duration"]),
        "avg_load_time": stats["avg_load_time"],
        "avg_hits_per_session": stats["avg_hits_per_session"],
    }


@dlt.resource(
    name="hourly_stats",
    write_disposition=UPSERT,
    primary_key=("service_uuid", "hour"),
    columns=_columns(
        service_uuid="text",
        date="date",
        hour="timestamp",
        session_count="bigint",
        hit_count="bigint",
    ),
)
def hourly_stats(
    settings: ShynetConfig, fetch: Fetch
) -> Iterator[list[dict[str, Any]]]:
    """Sessions and hits per service per hour, from the dashboard chart. Hours still to come are omitted."""
    for day in _days(settings):
        rows = []
        for service in fetch(day):
            stats = service["stats"]
            if stats["chart_granularity"] != "hourly":
                raise ShynetError(
                    f"expected an hourly chart for {day}, got {stats['chart_granularity']!r}"
                )
            chart = stats["chart_data"]
            rows.extend(
                {
                    "service_uuid": service["uuid"],
                    "date": day,
                    # str() of an aware datetime in the server's time zone
                    "hour": datetime.fromisoformat(label),
                    "session_count": sessions,
                    "hit_count": hits,
                }
                for label, sessions, hits in zip(
                    chart["labels"], chart["sessions"], chart["hits"], strict=True
                )
            )
        yield rows


def _breakdown(stats_key: str, field: str) -> Callable[..., DltResource]:
    """A resource for one of the dashboard's breakdowns, e.g. `daily_referrers`."""

    @dlt.resource(
        name=f"daily_{stats_key}",
        write_disposition=UPSERT,
        primary_key=("service_uuid", "date", field),
        columns={
            **_columns(service_uuid="text", date="date"),
            field: {"data_type": "text"},
            **_columns(count="bigint"),
        },
    )
    def breakdown(
        settings: ShynetConfig, fetch: Fetch
    ) -> Iterator[list[dict[str, Any]]]:
        for day in _days(settings):
            yield [
                {
                    "service_uuid": service["uuid"],
                    "date": day,
                    field: row[field],
                    "count": row["count"],
                }
                for service in fetch(day)
                for row in service["stats"][stats_key]
            ]

    breakdown.__doc__ = (
        f"Daily {stats_key.replace('_', ' ')} per service, with their counts."
    )
    return breakdown


BREAKDOWN_RESOURCES = tuple(_breakdown(key, field) for key, field in BREAKDOWNS.items())


@dlt.source(name="shynet")
def shynet_source(
    base_url: str = dlt.secrets.value,
    api_key: str = dlt.secrets.value,
    service_uuids: list[str] | None = None,
    initial_start_date: str | None = None,
    lookback_days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[DltResource]:
    """Daily traffic stats from a Shynet instance's dashboard API.

    dlt reads each argument from `[sources.shynet]` in .dlt/config.toml, and `base_url` and
    `api_key` from .dlt/secrets.toml (or SOURCES__SHYNET__BASE_URL / SOURCES__SHYNET__API_KEY),
    unless passed explicitly. ShynetConfig validates them all before any request is made.
    """
    raw = {
        "base_url": base_url,
        "api_key": api_key,
        "service_uuids": service_uuids,
        "initial_start_date": initial_start_date,
        "lookback_days": lookback_days,
        "start_date": start_date,
        "end_date": end_date,
    }
    settings = ShynetConfig.model_validate(
        {key: value for key, value in raw.items() if value is not None}
    )
    # Every resource reads the same days, so each day is fetched once and kept for the run. dlt doesn't
    # read the resources in lockstep, so a bounded cache could refetch; a day is a few KB for a small
    # site, so even a year's backfill stays small.
    fetch: Fetch = functools.cache(functools.partial(_dashboard, settings))
    return [
        services(settings, fetch),
        daily_stats(settings, fetch),
        hourly_stats(settings, fetch),
        *(resource(settings, fetch) for resource in BREAKDOWN_RESOURCES),
    ]
