"""Validated settings for the Shynet source.

dlt resolves the raw values from .dlt/config.toml and .dlt/secrets.toml; these models check them
before any request is made.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

API_PATH = "/api/v1/dashboard/"


def today() -> date:
    """The current UTC date. Shynet's days follow its server's TIME_ZONE, so lookback_days absorbs the offset."""
    return datetime.now(UTC).date()


class ShynetConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    base_url: HttpUrl
    api_key: SecretStr
    service_uuids: tuple[UUID, ...] = ()
    # First day of the first run; later runs resume from the resource state
    initial_start_date: date = Field(
        default_factory=lambda: today() - timedelta(days=30)
    )
    lookback_days: int = Field(default=3, ge=0)
    # An explicit window for one run (e.g. a backfill); overrides the resource state
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: HttpUrl) -> HttpUrl:
        # The token is sent in a header on every request
        if value.scheme != "https":
            raise ValueError(
                "base_url must use https, since the API token is sent with every request"
            )
        if value.query or value.fragment:
            raise ValueError("base_url must not have a query or fragment")
        return value

    @field_validator("api_key")
    @classmethod
    def _check_api_key(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value().strip()
        if not token or token.startswith("<"):
            raise ValueError(
                "api_key is empty or still the placeholder; set it in .dlt/secrets.toml"
            )
        return SecretStr(token)

    @field_validator("service_uuids")
    @classmethod
    def _check_service_uuids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        # Each UUID is a separate request, so a repeat would load the service's rows twice
        duplicates = sorted({str(u) for u in value if value.count(u) > 1})
        if duplicates:
            raise ValueError(f"duplicate service_uuids: {duplicates}")
        return value

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError(
                f"start_date {self.start_date} is after end_date {self.end_date}"
            )
        return self

    @property
    def endpoint(self) -> str:
        return str(self.base_url).rstrip("/") + API_PATH
