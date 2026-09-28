"""dlt source for the Alpha Vantage market and economic data API.

Docs: https://www.alphavantage.co/documentation/
"""

import time
from collections.abc import Iterator
from typing import Any

import dlt
from dlt.sources import DltResource
from dlt.sources.helpers.requests import Client, RequestException

from financial.config import AlphaVantageConfig

BASE_URL = "https://www.alphavantage.co/query"

_client = Client(raise_for_status=False)
_last_request_at = 0.0


class AlphaVantageError(Exception):
    """Raised when Alpha Vantage returns an error, rate limit, or premium-only notice."""


def _get(settings: AlphaVantageConfig, function: str, **params: str) -> dict[str, Any]:
    global _last_request_at
    time.sleep(
        max(0.0, _last_request_at + settings.min_request_interval - time.monotonic())
    )
    try:
        response = _client.get(
            BASE_URL,
            params={
                "function": function,
                **params,
                "apikey": settings.api_key.get_secret_value(),
            },
        )
    except RequestException as e:
        # requests' own messages include the URL, and with it the key
        raise AlphaVantageError(f"{function}: {type(e).__name__}") from None
    finally:
        _last_request_at = time.monotonic()
    if not response.ok:
        raise AlphaVantageError(f"{function}: HTTP {response.status_code}")
    return response.json()


def _query(
    settings: AlphaVantageConfig, function: str, **params: str
) -> dict[str, Any]:
    # Errors and rate limits come back as HTTP 200 with a single message key.
    # The burst limit is enforced over a window, so back off and retry it; the
    # daily limit shares the same message and will still fail after retries.
    for backoff in (*settings.rate_limit_backoff, None):
        payload = _get(settings, function, **params)
        message = payload.get("Information") or payload.get("Note")
        if backoff is None or not (message and "sparingly" in message):
            break
        time.sleep(backoff)

    for key in ("Error Message", "Information", "Note"):
        if key in payload:
            # Alpha Vantage echoes the API key in its rate-limit message
            raise AlphaVantageError(settings.redact(f"{function}: {payload[key]}"))
    return payload


def _to_float(value: str) -> float | None:
    # Alpha Vantage uses "." and "None" for missing values
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
def daily_prices(settings: AlphaVantageConfig) -> Iterator[list[dict[str, Any]]]:
    """Daily OHLCV bars per symbol."""
    for symbol in settings.symbols:
        payload = _query(
            settings, "TIME_SERIES_DAILY", symbol=symbol, outputsize=settings.outputsize
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
    # scd2 keeps every version of a company's fundamentals, with validity columns
    # _dlt_valid_from / _dlt_valid_to (null while current). merge_key limits retirement
    # to the symbols in this load, so a partial run (--symbols) doesn't retire the rest.
    write_disposition={"disposition": "merge", "strategy": "scd2"},
    merge_key="symbol",
)
def company_overviews(settings: AlphaVantageConfig) -> Iterator[dict[str, Any]]:
    """Company fundamentals, one row per symbol. Values are left as returned for dbt to type."""
    for symbol in settings.symbols:
        overview = _query(settings, "OVERVIEW", symbol=symbol)
        # ETFs and unknown symbols return an empty object
        if overview:
            yield overview


@dlt.resource(
    name="economic_indicators",
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    primary_key=("indicator", "date"),
    columns={"date": {"data_type": "date"}},
)
def economic_indicators(settings: AlphaVantageConfig) -> Iterator[list[dict[str, Any]]]:
    """US macro time series (GDP, CPI, rates, ...), one row per indicator per period."""
    for indicator in settings.indicators:
        payload = _query(settings, indicator.function, **indicator.params())
        yield [
            {
                "indicator": indicator.function,
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
    indicators: list[dict[str, str]] | None = None,
    outputsize: str = "compact",
    api_key: str = dlt.secrets.value,
) -> list[DltResource]:
    """Stock prices, company fundamentals and economic indicators from Alpha Vantage.

    dlt reads each argument from `[sources.alpha_vantage]` in .dlt/config.toml, and
    `api_key` from .dlt/secrets.toml (or SOURCES__ALPHA_VANTAGE__API_KEY), unless passed
    explicitly. AlphaVantageConfig validates them all before any request is made.
    """
    raw: dict[str, Any] = {
        "api_key": api_key,
        "symbols": symbols,
        "outputsize": outputsize,
    }
    if indicators is not None:
        raw["indicators"] = indicators
    settings = AlphaVantageConfig.model_validate(raw)
    return [
        daily_prices(settings),
        company_overviews(settings),
        economic_indicators(settings),
    ]
