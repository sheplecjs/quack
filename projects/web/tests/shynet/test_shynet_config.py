from datetime import date

import pytest
from pydantic import ValidationError
from web.ingestion.shynet.config import ShynetConfig

TOKEN = "TESTTOKEN123SECRET"  # pragma: allowlist secret
UUID = "2f1e0b8c-3d4a-4c5b-9e6f-7a8b9c0d1e2f"


def make(**overrides):
    return ShynetConfig.model_validate(
        {"base_url": "https://shynet.example.com", "api_key": TOKEN, **overrides}
    )


def test_api_key_is_masked_in_repr_and_str():
    config = make()
    assert TOKEN not in repr(config)
    assert TOKEN not in str(config)
    assert config.api_key.get_secret_value() == TOKEN


@pytest.mark.parametrize("token", ["", "   ", "<paste-your-shynet-api-key-here>"])
def test_rejects_missing_or_placeholder_api_key(token):
    with pytest.raises(ValidationError, match="placeholder"):
        make(api_key=token)


def test_validation_errors_do_not_echo_the_api_key():
    with pytest.raises(ValidationError) as excinfo:
        make(service_uuids=["not-a-uuid"])
    assert TOKEN not in str(excinfo.value)


@pytest.mark.parametrize(
    ("base_url", "endpoint"),
    [
        ("https://shynet.example.com", "https://shynet.example.com/api/v1/dashboard/"),
        ("https://example.com/shynet/", "https://example.com/shynet/api/v1/dashboard/"),
    ],
)
def test_endpoint_is_under_the_base_url(base_url, endpoint):
    assert make(base_url=base_url).endpoint == endpoint


@pytest.mark.parametrize(
    "base_url", ["http://shynet.example.com", "https://x.com/?a=1", "shynet"]
)
def test_rejects_insecure_or_malformed_base_urls(base_url):
    with pytest.raises(ValidationError):
        make(base_url=base_url)


def test_rejects_invalid_or_duplicate_service_uuids():
    # Shynet ignores an invalid uuid and returns every service, so it must fail here
    with pytest.raises(ValidationError):
        make(service_uuids=["not-a-uuid"])
    with pytest.raises(ValidationError, match="duplicate"):
        make(service_uuids=[UUID, UUID.upper()])


def test_rejects_a_window_that_ends_before_it_starts():
    with pytest.raises(ValidationError, match="after end_date"):
        make(start_date="2026-10-02", end_date="2026-10-01")


def test_parses_dates_and_defaults():
    config = make(initial_start_date="2026-01-01")
    assert config.initial_start_date == date(2026, 1, 1)
    assert config.lookback_days == 3
    assert config.service_uuids == ()


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        make(service_uuid=UUID)
