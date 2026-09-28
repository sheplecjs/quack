import pytest
from financial import sources
from financial.config import AlphaVantageConfig

KEY = "TESTKEY123SECRET"  # pragma: allowlist secret


@pytest.fixture
def settings():
    return AlphaVantageConfig(
        api_key=KEY,
        symbols=("JNJ",),
        min_request_interval=0,
        rate_limit_backoff=(0, 0),
    )


def test_rate_limit_error_does_not_leak_the_api_key(settings, monkeypatch):
    # Alpha Vantage echoes the key in its rate-limit message
    payload = {
        "Information": f"We have detected your API key as {KEY} and our standard API rate limit is 25"
    }
    monkeypatch.setattr(sources, "_get", lambda *a, **kw: payload)

    with pytest.raises(sources.AlphaVantageError) as excinfo:
        sources._query(settings, "OVERVIEW", symbol="JNJ")
    assert KEY not in str(excinfo.value)
    assert "**********" in str(excinfo.value)


def test_burst_limit_is_retried_once_per_backoff(settings, monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return {
            "Information": "Please consider spreading out your free API requests more sparingly"
        }

    monkeypatch.setattr(sources, "_get", fake_get)
    with pytest.raises(sources.AlphaVantageError):
        sources._query(settings, "OVERVIEW", symbol="JNJ")
    # One initial attempt plus one retry per backoff entry
    assert len(calls) == 1 + len(settings.rate_limit_backoff)


def test_source_validates_config_before_any_request(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda *a, **kw: pytest.fail("made a request"))
    with pytest.raises(Exception, match="duplicate ticker symbols"):
        sources.alpha_vantage_source(symbols=["JNJ", "JNJ"], api_key=KEY)


def test_source_parses_indicators_from_config_dicts():
    source = sources.alpha_vantage_source(
        symbols=["JNJ"],
        indicators=[{"function": "CPI", "interval": "semiannual"}],
        api_key=KEY,
    )
    assert set(source.resources) == {
        "daily_prices",
        "company_overviews",
        "economic_indicators",
    }
