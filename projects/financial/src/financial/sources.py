"""dlt source for the Alpha Vantage market and economic data API.

Docs: https://www.alphavantage.co/documentation/
"""

import time
from collections.abc import Iterator, Sequence
from typing import Any

import dlt
from dlt.sources import DltResource
from dlt.sources.helpers.requests import Client, RequestException

BASE_URL = "https://www.alphavantage.co/query"
MIN_REQUEST_INTERVAL = 1.2
RATE_LIMIT_BACKOFF = (2, 5, 10, 0)

DEFAULT_INDICATORS: dict[str, dict[str, str]] = {
    "REAL_GDP": {"interval": "quarterly"},
    "CPI": {"interval": "monthly"},
    "INFLATION": {},
    "FEDERAL_FUNDS_RATE": {"interval": "monthly"},
    "TREASURY_YIELD": {"interval": "monthly", "maturity": "10year"},
    "UNEMPLOYMENT": {},
}

_client = Client(raise_for_status=False)
_last_request_at = 0.0


class AlphaVantageError(Exception):
    """Raised when Alpha Vantage returns an error, rate limit, or premium-only notice."""


def _get(api_key: str, function: str, **params: str) -> dict[str, Any]:
    global _last_request_at
    time.sleep(max(0.0, _last_request_at + MIN_REQUEST_INTERVAL - time.monotonic()))
    try:
        response = _client.get(
            BASE_URL, params={"function": function, **params, "apikey": api_key}
        )
    except RequestException as e:
        raise AlphaVantageError(f"{function}: {type(e).__name__}") from None
    finally:
        _last_request_at = time.monotonic()
    if not response.ok:
        raise AlphaVantageError(f"{function}: HTTP {response.status_code}")
    return response.json()


def _query(api_key: str, function: str, **params: str) -> dict[str, Any]:
    for backoff in RATE_LIMIT_BACKOFF:
        payload = _get(api_key, function, **params)
        message = payload.get("Information") or payload.get("Note")
        if not (message and "sparingly" in message):
            break
        time.sleep(backoff)

    for key in ("Error Message", "Information", "Note"):
        if key in payload:
            raise AlphaVantageError(f"{function}: {payload[key]}")
    return payload


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


@dlt.resource(
    name="daily_prices",
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    primary_key=("symbol", "date"),
    columns={"date": {"data_type": "date"}},
)
def daily_prices(
    symbols: Sequence[str], api_key: str, outputsize: str = "compact"
) -> Iterator[list[dict[str, Any]]]:
    """Daily OHLCV bars per symbol. `compact` is the last 100 days; `full` is premium-only."""
    for symbol in symbols:
        payload = _query(
            api_key, "TIME_SERIES_DAILY", symbol=symbol, outputsize=outputsize
        )
        yield [
            {
                "symbol": symbol,
                "date": day,
                "open": float(bar["1. open"]),
                "high": float(bar["2. high"]),
                "low": float(bar["3. low"]),
                "close": float(bar["4. close"]),
                "volume": int(bar["5. volume"]),
            }
            for day, bar in payload["Time Series (Daily)"].items()
        ]


@dlt.resource(
    name="company_overviews",
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    primary_key="symbol",
)
def company_overviews(symbols: Sequence[str], api_key: str) -> Iterator[dict[str, Any]]:
    """Company fundamentals, one row per symbol. Values are left as returned for dbt to type."""
    for symbol in symbols:
        overview = _query(api_key, "OVERVIEW", symbol=symbol)
        if overview:
            yield overview


@dlt.resource(
    name="economic_indicators",
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    primary_key=("indicator", "date"),
    columns={"date": {"data_type": "date"}},
)
def economic_indicators(
    indicators: dict[str, dict[str, str]], api_key: str
) -> Iterator[list[dict[str, Any]]]:
    """US macro time series (GDP, CPI, rates, ...), one row per indicator per period."""
    for indicator, params in indicators.items():
        payload = _query(api_key, indicator, **params)
        yield [
            {
                "indicator": indicator,
                "name": payload["name"],
                "interval": payload["interval"],
                "unit": payload["unit"],
                "date": point["date"],
                "value": _to_float(point["value"]),
            }
            for point in payload["data"]
        ]


@dlt.source(name="alpha_vantage")
def alpha_vantage_source(
    symbols: list[str] = dlt.config.value,
    indicators: dict[str, dict[str, str]] | None = None,
    api_key: str = dlt.secrets.value,
) -> list[DltResource]:
    """Stock prices, company fundamentals and economic indicators from Alpha Vantage.

    `symbols` is read from `[sources.alpha_vantage]` in .dlt/config.toml and
    `api_key` from `[sources.alpha_vantage]` in .dlt/secrets.toml (or the
    SOURCES__ALPHA_VANTAGE__API_KEY env var) unless passed explicitly.
    """
    return [
        daily_prices(symbols, api_key),
        company_overviews(symbols, api_key),
        economic_indicators(indicators or DEFAULT_INDICATORS, api_key),
    ]
