import sqlite3
from datetime import UTC, datetime, timedelta

import dlt
import pytest
from pydantic import ValidationError
from web.ingestion.shynet_db import source as sources
from web.ingestion.shynet_db.config import ShynetDbConfig

PASSWORD = "TESTPASSWORD123SECRET"  # pragma: allowlist secret
URL = f"postgresql://reader:{PASSWORD}@db.example.com/shynet?sslmode=require"
T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture
def shynet(tmp_path):
    """A SQLite copy of Shynet's two tables, including the columns the read-only role can't see."""
    path = tmp_path / "shynet.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        """
        create table analytics_session (
            uuid text primary key, service_id text, identifier text, start_time timestamp,
            last_seen timestamp, user_agent text, browser text, device text, device_type text,
            os text, ip text, asn text, country text, longitude real, latitude real,
            time_zone text, is_bounce boolean
        );
        create table analytics_hit (
            id integer primary key, session_id text, initial boolean, start_time timestamp,
            last_seen timestamp, heartbeats integer, tracker text, location text, referrer text,
            load_time real, service_id text
        );
        """
    )
    db.commit()
    yield db, f"sqlite:///{path}"
    db.close()


def add_session(db, uuid, last_seen, ip="203.0.113.7"):
    db.execute(
        "insert or replace into analytics_session values "
        "(?, 'svc', '', ?, ?, 'Mozilla/5.0', 'Firefox', 'Other', 'DESKTOP', 'Linux', ?, 'ISP', 'CA', 1.0, 2.0, 'America/Toronto', 1)",
        (uuid, T0.isoformat(), last_seen.isoformat(), ip),
    )
    db.commit()


def add_hit(db, hit_id, session, last_seen, heartbeats=0):
    db.execute(
        "insert or replace into analytics_hit values (?, ?, 1, ?, ?, ?, 'JS', 'https://example.com/', '', 412.5, 'svc')",
        (hit_id, session, T0.isoformat(), last_seen.isoformat(), heartbeats),
    )
    db.commit()


@pytest.fixture
def pipeline(tmp_path):
    return dlt.pipeline(
        pipeline_name="shynet_db_test",
        pipelines_dir=str(tmp_path / "pipelines"),
        destination=dlt.destinations.duckdb(str(tmp_path / "data.duckdb")),
        dataset_name="shynet_db",
    )


def query(pipeline, sql):
    with pipeline.sql_client() as client:
        return client.execute_sql(sql)


def columns(pipeline, table):
    rows = query(
        pipeline,
        f"select column_name from information_schema.columns where table_schema = 'shynet_db' "
        f"and table_name = '{table}' and not starts_with(column_name, '_dlt') order by ordinal_position",
    )
    return [name for (name,) in rows]


def test_loads_only_the_granted_columns_under_new_names(shynet, pipeline):
    db, url = shynet
    add_session(db, "s1", T0)
    add_hit(db, 1, "s1", T0)
    pipeline.run(sources.shynet_tables(url, lag_seconds=3600))

    # In the source table's column order
    assert set(columns(pipeline, "sessions")) == set(
        sources.TABLES["analytics_session"][2]
    )
    assert set(columns(pipeline, "hits")) == set(sources.TABLES["analytics_hit"][2])
    for private in ("ip", "latitude", "longitude", "identifier"):
        assert private not in columns(pipeline, "sessions")


def test_updated_rows_are_upserted(shynet, pipeline):
    db, url = shynet
    add_session(db, "s1", T0)
    add_hit(db, 1, "s1", T0)
    pipeline.run(sources.shynet_tables(url, lag_seconds=0))

    # The page stays open: Shynet bumps last_seen and heartbeats on the same rows
    add_session(db, "s1", T0 + timedelta(minutes=5))
    add_hit(db, 1, "s1", T0 + timedelta(minutes=5), heartbeats=12)
    pipeline.run(sources.shynet_tables(url, lag_seconds=0))

    assert query(pipeline, "select count(*), max(heartbeats) from hits") == [(1, 12)]
    assert query(pipeline, "select count(*) from sessions") == [(1,)]


def test_a_row_committed_late_within_the_lag_is_still_read(shynet, pipeline):
    db, url = shynet
    add_session(db, "s1", T0 + timedelta(minutes=30))
    pipeline.run(sources.shynet_tables(url, lag_seconds=3600)[0])

    # Written after the first load, but stamped before its cursor
    add_session(db, "s2", T0 + timedelta(minutes=10))
    pipeline.run(sources.shynet_tables(url, lag_seconds=3600)[0])
    assert query(pipeline, "select uuid from sessions order by uuid") == [
        ("s1",),
        ("s2",),
    ]


def test_without_a_lag_a_late_row_is_skipped(shynet, pipeline):
    db, url = shynet
    add_session(db, "s1", T0 + timedelta(minutes=30))
    pipeline.run(sources.shynet_tables(url, lag_seconds=0)[0])
    add_session(db, "s2", T0 + timedelta(minutes=10))
    pipeline.run(sources.shynet_tables(url, lag_seconds=0)[0])
    assert query(pipeline, "select uuid from sessions") == [("s1",)]


def test_source_validates_credentials_before_connecting():
    # An unresolvable host would hang or fail on connect; validation must fail first
    with pytest.raises(Exception, match="sslmode=require"):
        sources.shynet_db_source(credentials=URL.removesuffix("?sslmode=require"))


def test_building_the_source_does_not_connect():
    source = sources.shynet_db_source(credentials=URL)
    assert set(source.resources) == {"sessions", "hits"}


@pytest.mark.parametrize(
    "url",
    [
        URL.removesuffix("?sslmode=require"),
        URL.replace("require", "prefer"),
        URL.replace("require", "disable"),
        URL.replace("postgresql", "mysql"),
        "postgresql://reader@db.example.com/shynet?sslmode=require",
        "postgresql://reader:<password>@db.example.com/shynet?sslmode=require",
        "not a url",
    ],
)
def test_rejects_insecure_or_incomplete_credentials(url):
    with pytest.raises(ValidationError) as excinfo:
        ShynetDbConfig(credentials=url)
    assert PASSWORD not in str(excinfo.value)


@pytest.mark.parametrize(
    "url", [URL, URL.replace("postgresql://", "postgresql+psycopg://")]
)
def test_the_psycopg_driver_is_pinned(url):
    # A bare postgresql:// means psycopg2 on SQLAlchemy < 2.1, which the project doesn't install
    config = ShynetDbConfig(credentials=url)
    assert config.credentials.get_secret_value().startswith(
        "postgresql+psycopg://reader:"
    )


def test_rejects_other_postgres_drivers():
    with pytest.raises(ValidationError, match="psycopg driver") as excinfo:
        ShynetDbConfig(
            credentials=URL.replace("postgresql://", "postgresql+psycopg2://")
        )
    assert PASSWORD not in str(excinfo.value)


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_accepts_tls_modes(mode):
    config = ShynetDbConfig(credentials=URL.replace("require", mode))
    assert PASSWORD not in repr(config)
    assert config.credentials.get_secret_value().endswith(f"sslmode={mode}")
