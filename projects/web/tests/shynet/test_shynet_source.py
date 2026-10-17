import json
from datetime import UTC, date, datetime, timedelta, timezone

import dlt
import pytest
from web.ingestion.shynet import source as sources

TOKEN = "TESTTOKEN123SECRET"  # pragma: allowlist secret
SERVICE = "2f1e0b8c-3d4a-4c5b-9e6f-7a8b9c0d1e2f"
SERVER_TZ = timezone(timedelta(hours=-4))


def stats(day: date) -> dict:
    """One day of Service.get_core_stats(), as the API serialises it."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=SERVER_TZ)
    hours = [midnight + timedelta(hours=h) for h in range(24)]
    return {
        "currently_online": 1,
        "session_count": 2,
        "hit_count": 3,
        "has_hits": True,
        "bounce_rate_pct": 50.0,
        "avg_session_duration": "P0DT00H01M30.500000S",
        "avg_load_time": 412.5,
        "avg_hits_per_session": 1.5,
        "locations": [
            {"location": "https://example.com/", "count": 2},
            {"location": "https://example.com/about", "count": 1},
        ],
        "referrers": [
            {"referrer": "", "count": 1},
            {"referrer": "https://news.ycombinator.com/", "count": 1},
        ],
        "countries": [{"country": "CA", "count": 2}],
        "operating_systems": [{"os": "Linux", "count": 2}],
        "browsers": [{"browser": "Firefox", "count": 2}],
        "devices": [{"device": "Other", "count": 2}],
        "device_types": [{"device_type": "DESKTOP", "count": 2}],
        "chart_data": {
            "sessions": [1, 1] + [0] * 22,
            "hits": [2, 1] + [0] * 22,
            "labels": [str(hour) for hour in hours],
        },
        "chart_tooltip_format": "MM/dd HH:mm",
        "chart_granularity": "hourly",
        "online": True,
        "compare": {},
    }


def payload(day: date) -> dict:
    return {
        "services": [
            {
                "name": "Profile",
                "uuid": SERVICE,
                "link": "https://example.com",
                "stats": stats(day),
            }
        ]
    }


@pytest.fixture
def requests(monkeypatch):
    """Record each request's params and answer with one day of stats."""
    calls = []

    def fake_get(settings, params):
        calls.append(params)
        return payload(date.fromisoformat(params["startDate"]))

    monkeypatch.setattr(sources, "_get", fake_get)
    return calls


@pytest.fixture
def pipeline(tmp_path):
    return dlt.pipeline(
        pipeline_name="shynet_test",
        pipelines_dir=str(tmp_path / "pipelines"),
        destination=dlt.destinations.duckdb(str(tmp_path / "data.duckdb")),
        dataset_name="shynet",
    )


def source(**kwargs):
    return sources.shynet_source(
        base_url="https://shynet.example.com", api_key=TOKEN, **kwargs
    )


def rows(pipeline, table):
    with pipeline.sql_client() as client:
        return client.execute_sql(f"select * from {table}")


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("P0DT00H01M30.500000S", 90.5),
        ("P1DT02H00M00S", 93600.0),
        ("-P0DT00H00M05S", -5.0),
        (12.25, 12.25),
        (None, None),
    ],
)
def test_durations_become_seconds(value, seconds):
    assert sources._duration_seconds(value) == seconds


def test_unexpected_duration_fails():
    with pytest.raises(sources.ShynetError):
        sources._duration_seconds("5 minutes")


def test_each_day_is_requested_once_and_loads_every_table(requests, pipeline):
    pipeline.run(source(start_date="2026-10-01", end_date="2026-10-02"))

    # Ten resources share one request per day
    assert sorted(r["startDate"] for r in requests) == ["2026-10-01", "2026-10-02"]
    assert all(r["endDate"] == r["startDate"] for r in requests)
    assert len(rows(pipeline, "services")) == 1
    assert len(rows(pipeline, "daily_stats")) == 2
    assert len(rows(pipeline, "hourly_stats")) == 48
    assert len(rows(pipeline, "daily_locations")) == 4
    assert len(rows(pipeline, "daily_device_types")) == 2


def test_daily_stats_parse_the_duration(requests, pipeline):
    pipeline.run(
        source(start_date="2026-10-01", end_date="2026-10-01").with_resources(
            "daily_stats"
        )
    )
    with pipeline.sql_client() as client:
        assert client.execute_sql("select avg_session_duration from daily_stats") == [
            (90.5,)
        ]


def test_hourly_stats_keep_the_server_offset(requests, pipeline):
    pipeline.run(
        source(start_date="2026-10-01", end_date="2026-10-01").with_resources(
            "hourly_stats"
        )
    )
    with pipeline.sql_client() as client:
        (first,) = client.execute_sql("select min(hour) from hourly_stats")[0]
    assert first == datetime(2026, 10, 1, 4, tzinfo=UTC)


def test_reloading_a_day_upserts(requests, pipeline):
    for _ in range(2):
        pipeline.run(source(start_date="2026-10-01", end_date="2026-10-01"))
    assert len(rows(pipeline, "daily_stats")) == 1
    assert len(rows(pipeline, "daily_referrers")) == 2


def test_later_runs_resume_from_the_last_day_minus_the_lookback(requests, pipeline):
    pipeline.run(
        source(initial_start_date="2026-10-01", end_date="2026-10-05").with_resources(
            "daily_stats"
        )
    )
    requests.clear()
    pipeline.run(
        source(lookback_days=1, end_date="2026-10-07").with_resources("daily_stats")
    )

    assert [r["startDate"] for r in requests] == [
        "2026-10-04",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    ]


def test_a_backfill_does_not_move_the_next_start_back(requests, pipeline):
    pipeline.run(
        source(start_date="2026-10-05", end_date="2026-10-05").with_resources(
            "daily_stats"
        )
    )
    pipeline.run(
        source(start_date="2026-09-01", end_date="2026-09-02").with_resources(
            "daily_stats"
        )
    )
    requests.clear()
    pipeline.run(
        source(lookback_days=0, end_date="2026-10-06").with_resources("daily_stats")
    )

    assert [r["startDate"] for r in requests] == ["2026-10-05", "2026-10-06"]


def test_service_uuids_are_requested_one_by_one(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sources,
        "_get",
        lambda settings, params: calls.append(params) or {"services": []},
    )
    settings = sources.ShynetConfig(
        base_url="https://shynet.example.com", api_key=TOKEN, service_uuids=(SERVICE,)
    )
    # An unknown or unshared uuid returns no services
    with pytest.raises(sources.ShynetError, match="isn't shared"):
        sources._dashboard(settings, date(2026, 10, 1))
    assert calls == [
        {"startDate": "2026-10-01", "endDate": "2026-10-01", "uuid": SERVICE}
    ]


def test_a_daily_chart_fails(monkeypatch, pipeline):
    def fake_get(settings, params):
        response = payload(date(2026, 10, 1))
        response["services"][0]["stats"]["chart_granularity"] = "daily"
        return response

    monkeypatch.setattr(sources, "_get", fake_get)
    with pytest.raises(Exception, match="expected an hourly chart"):
        pipeline.run(
            source(start_date="2026-10-01", end_date="2026-10-01").with_resources(
                "hourly_stats"
            )
        )


def test_rejected_token_is_reported_without_echoing_it(monkeypatch):
    class Forbidden:
        status_code = 403
        ok = False

    monkeypatch.setattr(sources._client, "get", lambda *a, **kw: Forbidden())
    settings = sources.ShynetConfig(
        base_url="https://shynet.example.com", api_key=TOKEN
    )
    with pytest.raises(sources.ShynetError, match="rejected the API token") as excinfo:
        sources._get(settings, {})
    assert TOKEN not in str(excinfo.value)


class Response:
    """A stand-in for a requests response that answered 200."""

    status_code = 200
    ok = True

    def __init__(self, text, content_type="application/json"):
        self.text = text
        self.headers = {"Content-Type": content_type}

    def json(self):
        # Raises json.JSONDecodeError (a ValueError) on a non-JSON body, as requests does
        return json.loads(self.text)


@pytest.mark.parametrize(
    ("body", "content_type", "detail"),
    [
        ("<html>Sign in</html>", "text/html; charset=utf-8", "got text/html"),
        ('{"detail": "not found"}', "application/json", "no list of services"),
        ("[]", "application/json", "no list of services"),
    ],
)
def test_a_200_that_isnt_the_dashboard_says_to_check_base_url(
    monkeypatch, body, content_type, detail
):
    monkeypatch.setattr(
        sources._client, "get", lambda *a, **kw: Response(body, content_type)
    )
    settings = sources.ShynetConfig(
        base_url="https://shynet.example.com", api_key=TOKEN
    )
    with pytest.raises(sources.ShynetError, match="check base_url") as excinfo:
        sources._get(settings, {})
    assert detail in str(excinfo.value)
    assert TOKEN not in str(excinfo.value)


def test_source_validates_config_before_any_request(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda *a, **kw: pytest.fail("made a request"))
    with pytest.raises(Exception, match="https"):
        sources.shynet_source(base_url="http://shynet.example.com", api_key=TOKEN)
