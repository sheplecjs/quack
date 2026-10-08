"""Validated settings for the Alpha Vantage source.

dlt resolves the raw values from .dlt/config.toml and .dlt/secrets.toml; these models check them
before any request is made.
"""

import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

OutputSize = Literal["compact", "full"]
IndicatorFunction = Literal[
    "REAL_GDP",
    "REAL_GDP_PER_CAPITA",
    "TREASURY_YIELD",
    "FEDERAL_FUNDS_RATE",
    "CPI",
    "INFLATION",
    "RETAIL_SALES",
    "DURABLES",
    "UNEMPLOYMENT",
    "NONFARM_PAYROLL",
]
Interval = Literal["daily", "weekly", "monthly", "quarterly", "semiannual", "annual"]
Maturity = Literal["3month", "2year", "5year", "7year", "10year", "30year"]

# Intervals each function accepts; functions not listed take no interval
INDICATOR_INTERVALS: dict[str, frozenset[str]] = {
    "REAL_GDP": frozenset({"annual", "quarterly"}),
    "TREASURY_YIELD": frozenset({"daily", "weekly", "monthly"}),
    "FEDERAL_FUNDS_RATE": frozenset({"daily", "weekly", "monthly"}),
    "CPI": frozenset({"monthly", "semiannual"}),
}

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")


class EconomicIndicator(BaseModel):
    """One economic series to load, with the query params its function accepts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    function: IndicatorFunction
    interval: Interval | None = None
    maturity: Maturity | None = None

    @model_validator(mode="after")
    def _check_params(self) -> Self:
        allowed = INDICATOR_INTERVALS.get(self.function, frozenset())
        if self.interval is not None and self.interval not in allowed:
            accepts = ", ".join(sorted(allowed)) or "no interval"
            raise ValueError(
                f"{self.function} accepts {accepts}, not interval={self.interval!r}"
            )
        if self.maturity is not None and self.function != "TREASURY_YIELD":
            raise ValueError(
                f"maturity only applies to TREASURY_YIELD, not {self.function}"
            )
        return self

    def params(self) -> dict[str, str]:
        """Query params for this series, omitting unset ones so the API uses its defaults."""
        return self.model_dump(exclude={"function"}, exclude_none=True)


DEFAULT_INDICATORS = (
    EconomicIndicator(function="REAL_GDP", interval="quarterly"),
    EconomicIndicator(function="CPI", interval="monthly"),
    EconomicIndicator(function="INFLATION"),
    EconomicIndicator(function="FEDERAL_FUNDS_RATE", interval="monthly"),
    EconomicIndicator(function="TREASURY_YIELD", interval="monthly", maturity="10year"),
    EconomicIndicator(function="UNEMPLOYMENT"),
)


class AlphaVantageConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    api_key: SecretStr
    symbols: tuple[str, ...] = Field(min_length=1)
    indicators: tuple[EconomicIndicator, ...] = DEFAULT_INDICATORS
    outputsize: OutputSize = "compact"
    min_request_interval: float = Field(default=1.2, ge=0)
    rate_limit_backoff: tuple[float, ...] = Field(default=(2, 5, 10))

    @field_validator("api_key")
    @classmethod
    def _check_api_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key or key.startswith("<"):
            raise ValueError(
                "api_key is empty or still the placeholder; set it in .dlt/secrets.toml"
            )
        return SecretStr(key)

    @field_validator("symbols")
    @classmethod
    def _check_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        symbols = tuple(s.strip().upper() for s in value)
        invalid = [s for s in symbols if not SYMBOL_PATTERN.match(s)]
        if invalid:
            raise ValueError(f"invalid ticker symbols: {invalid}")
        # upsert doesn't deduplicate: a repeated symbol would load duplicate rows
        duplicates = sorted({s for s in symbols if symbols.count(s) > 1})
        if duplicates:
            raise ValueError(f"duplicate ticker symbols: {duplicates}")
        return symbols

    @field_validator("rate_limit_backoff")
    @classmethod
    def _check_backoff(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(seconds < 0 for seconds in value):
            raise ValueError("rate_limit_backoff values must be >= 0")
        return value

    @field_validator("indicators")
    @classmethod
    def _check_indicators(
        cls, value: tuple[EconomicIndicator, ...]
    ) -> tuple[EconomicIndicator, ...]:
        # (indicator, date) is the table's primary key, so each function can appear once
        functions = [indicator.function for indicator in value]
        duplicates = sorted({f for f in functions if functions.count(f) > 1})
        if duplicates:
            raise ValueError(f"duplicate indicator functions: {duplicates}")
        return value

    def redact(self, text: str) -> str:
        """Mask the API key in text from outside, e.g. Alpha Vantage echoes it in rate-limit messages."""
        return text.replace(self.api_key.get_secret_value(), "**********")
