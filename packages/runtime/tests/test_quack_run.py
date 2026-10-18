import sys

import boto3
import pytest
from moto import mock_aws
from quack_runtime import cli

DATA = "quack-data"
ARTIFACTS = "quack-artifacts"
# Writes the second argument into the file named by the first
WRITE = [
    sys.executable,
    "-c",
    "import sys, pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])",
]


@pytest.fixture
def s3(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("QUACK_PROJECT", "financial")
    monkeypatch.setenv("QUACK_DATA_BUCKET", DATA)
    monkeypatch.setenv("QUACK_ARTIFACTS_BUCKET", ARTIFACTS)
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "data" / "data.duckdb"))
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=DATA)
        client.create_bucket(Bucket=ARTIFACTS)
        yield client


def db(tmp_path):
    return str(tmp_path / "data" / "data.duckdb")


def read(s3, bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()


def test_first_run_starts_empty_and_pushes_a_new_database(s3, tmp_path):
    assert (
        cli.main(["--pull-db", "--push-db", "--", *WRITE, db(tmp_path), "v1"], s3=s3)
        == 0
    )
    assert read(s3, DATA, "financial/data.duckdb") == "v1"


def test_pulls_the_database_before_running(s3, tmp_path):
    s3.put_object(Bucket=DATA, Key="financial/data.duckdb", Body=b"v1")
    copy = tmp_path / "copy"
    cat = [
        sys.executable,
        "-c",
        "import shutil, sys; shutil.copy(sys.argv[1], sys.argv[2])",
    ]
    assert cli.main(["--pull-db", "--", *cat, db(tmp_path), str(copy)], s3=s3) == 0
    assert copy.read_text() == "v1"


def test_failed_command_pushes_nothing(s3, tmp_path):
    s3.put_object(Bucket=DATA, Key="financial/data.duckdb", Body=b"v1")
    fail = [
        sys.executable,
        "-c",
        "import sys, pathlib; pathlib.Path(sys.argv[1]).write_text('bad'); sys.exit(3)",
    ]
    report = tmp_path / "report"
    report.mkdir()
    (report / "board.html").write_text("<html>")
    argv = [
        "--pull-db",
        "--push-db",
        "--push-dir",
        f"{report}=report",
        "--",
        *fail,
        db(tmp_path),
    ]
    assert cli.main(argv, s3=s3) == 3
    assert read(s3, DATA, "financial/data.duckdb") == "v1"
    assert "Contents" not in s3.list_objects_v2(Bucket=ARTIFACTS)


def test_push_refuses_to_overwrite_a_database_changed_by_another_run(
    s3, tmp_path, monkeypatch
):
    s3.put_object(Bucket=DATA, Key="financial/data.duckdb", Body=b"v1")
    real_run = cli.subprocess.run

    def run_while_another_run_writes(command, check):
        s3.put_object(Bucket=DATA, Key="financial/data.duckdb", Body=b"other run")
        return real_run(command, check=check)

    monkeypatch.setattr(cli.subprocess, "run", run_while_another_run_writes)
    with pytest.raises(cli.ConcurrentWriteError):
        cli.main(["--pull-db", "--push-db", "--", *WRITE, db(tmp_path), "v2"], s3=s3)
    assert read(s3, DATA, "financial/data.duckdb") == "other run"


def test_first_push_refuses_to_overwrite_a_database_created_meanwhile(
    s3, tmp_path, monkeypatch
):
    real_run = cli.subprocess.run

    def run_while_another_run_writes(command, check):
        s3.put_object(Bucket=DATA, Key="financial/data.duckdb", Body=b"other run")
        return real_run(command, check=check)

    monkeypatch.setattr(cli.subprocess, "run", run_while_another_run_writes)
    with pytest.raises(cli.ConcurrentWriteError):
        cli.main(["--pull-db", "--push-db", "--", *WRITE, db(tmp_path), "v1"], s3=s3)


def test_push_dir_uploads_under_the_project_prefix_with_content_types(s3, tmp_path):
    report = tmp_path / "report"
    (report / "nested").mkdir(parents=True)
    (report / "portfolio.html").write_text("<html>")
    (report / "nested" / "portfolio.png").write_bytes(b"png")
    assert (
        cli.main(
            ["--push-dir", f"{report}=report/", "--", sys.executable, "-c", "pass"],
            s3=s3,
        )
        == 0
    )
    html = s3.head_object(Bucket=ARTIFACTS, Key="financial/report/portfolio.html")
    png = s3.head_object(Bucket=ARTIFACTS, Key="financial/report/nested/portfolio.png")
    assert html["ContentType"] == "text/html"
    assert png["ContentType"] == "image/png"


@pytest.mark.parametrize(
    "argv",
    [
        ["--pull-db"],  # no command
        ["--push-db", "--", "true"],  # push without the pull it's conditional on
        ["--push-dir", "no-prefix", "--", "true"],
    ],
)
def test_rejects_invalid_arguments(s3, argv):
    with pytest.raises(SystemExit):
        cli.main(argv, s3=s3)


def test_requires_its_environment(monkeypatch):
    monkeypatch.delenv("QUACK_DATA_BUCKET", raising=False)
    with pytest.raises(SystemExit, match="QUACK_DATA_BUCKET"):
        cli.Settings.from_env({"QUACK_PROJECT": "financial", "DUCKDB_PATH": "x"})
