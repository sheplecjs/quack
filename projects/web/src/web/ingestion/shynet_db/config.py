"""Validated settings for the Shynet database source.

dlt resolves the raw values from .dlt/config.toml and .dlt/secrets.toml; this model checks them
before any connection is made.
"""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# libpq modes that refuse an unencrypted connection
TLS_MODES = frozenset({"require", "verify-ca", "verify-full"})
# The driver the project installs. A bare postgresql:// URL means whichever driver the installed
# SQLAlchemy defaults to (psycopg2 before 2.1), so it's pinned here.
DRIVERNAME = "postgresql+psycopg"


class ShynetDbConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    # postgresql://<user>:<password>@<host>/<database>?sslmode=require
    credentials: SecretStr
    # Rows whose last_seen is within this many seconds of the last load are read again, so a hit
    # or session committed late (after a later one was already read) isn't skipped
    lag_seconds: float = Field(default=3600, ge=0)

    @field_validator("credentials")
    @classmethod
    def _check_credentials(cls, value: SecretStr) -> SecretStr:
        # Messages never include the URL: it holds the password
        try:
            url = make_url(value.get_secret_value().strip())
        except ArgumentError:
            raise ValueError("credentials is not a database URL") from None
        if url.get_backend_name() != "postgresql":
            raise ValueError("credentials must be a postgresql:// URL")
        if url.drivername not in ("postgresql", DRIVERNAME):
            raise ValueError(
                f"credentials must use the psycopg driver: postgresql:// or {DRIVERNAME}://"
            )
        if not (url.username and url.password and url.host and url.database):
            raise ValueError("credentials needs a user, password, host and database")
        if url.password.startswith("<"):
            raise ValueError(
                "credentials still has the placeholder password; set it in .dlt/secrets.toml"
            )
        if url.query.get("sslmode") not in TLS_MODES:
            raise ValueError(
                "credentials must require TLS: end the URL with ?sslmode=require (or verify-ca / verify-full)"
            )
        return SecretStr(
            url.set(drivername=DRIVERNAME).render_as_string(hide_password=False)
        )
