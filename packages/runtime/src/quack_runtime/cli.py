"""The `quack-run` CLI: pull the DuckDB file from S3, run a command, push the results back.

A container's disk doesn't outlive its task, so each pipeline step (load, build, render) pulls the
project's database, runs, and pushes what it changed. dlt keeps its pipeline state inside the database,
so the next load resumes incrementally from what was pushed.

    quack-run --pull-db --push-db -- financial-load all
    quack-run --pull-db --push-dir /data/report=report -- bash render_reports.sh /data/report

Settings come from the environment, which the ECS task definition sets:

- QUACK_PROJECT: the project name, which prefixes every key (`<project>/data.duckdb`)
- QUACK_DATA_BUCKET: the bucket holding the database
- QUACK_ARTIFACTS_BUCKET: the bucket artifact folders are pushed to (needed for --push-dir)
- DUCKDB_PATH: the local database path, as the project's dlt destination and dbt profile read it

Nothing is pushed unless the command succeeds, so a failed step leaves S3 as it was.
"""

import argparse
import mimetypes
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

DB_FILENAME = "data.duckdb"
# S3 status codes for a conditional write that lost: the object changed (412), or another write to the
# same key was in flight (409)
CONFLICT_STATUSES = frozenset({409, 412})


class ConcurrentWriteError(RuntimeError):
    """The database in S3 changed after this step pulled it."""


@dataclass(frozen=True)
class Settings:
    project: str
    data_bucket: str
    artifacts_bucket: str | None
    db_path: Path

    @property
    def db_key(self) -> str:
        return f"{self.project}/{DB_FILENAME}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        missing = [
            k
            for k in ("QUACK_PROJECT", "QUACK_DATA_BUCKET", "DUCKDB_PATH")
            if not env.get(k)
        ]
        if missing:
            raise SystemExit(
                f"quack-run: missing environment variables: {', '.join(missing)}"
            )
        return cls(
            project=env["QUACK_PROJECT"],
            data_bucket=env["QUACK_DATA_BUCKET"],
            artifacts_bucket=env.get("QUACK_ARTIFACTS_BUCKET") or None,
            db_path=Path(env["DUCKDB_PATH"]).resolve(),
        )


def pull_db(s3: Any, settings: Settings) -> str | None:
    """Download the database; return its ETag, or None if there isn't one yet (the first run)."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        head = s3.head_object(Bucket=settings.data_bucket, Key=settings.db_key)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            log(
                f"no database at s3://{settings.data_bucket}/{settings.db_key}; starting empty"
            )
            return None
        raise
    etag = head["ETag"]
    # Pinned to the ETag just read, so the file and the ETag are the same version
    response = s3.get_object(
        Bucket=settings.data_bucket, Key=settings.db_key, IfMatch=etag
    )
    with settings.db_path.open("wb") as file:
        for chunk in response["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
            file.write(chunk)
    log(
        f"pulled s3://{settings.data_bucket}/{settings.db_key} ({head['ContentLength']} bytes)"
    )
    return etag


def push_db(s3: Any, settings: Settings, etag: str | None) -> None:
    """Upload the database only if S3 still holds the version pulled (or none, on the first run).

    A single PUT, so the database must stay under S3's 5 GB single-object limit.
    """
    condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    try:
        with settings.db_path.open("rb") as body:
            s3.put_object(
                Bucket=settings.data_bucket, Key=settings.db_key, Body=body, **condition
            )
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] in CONFLICT_STATUSES:
            raise ConcurrentWriteError(
                f"s3://{settings.data_bucket}/{settings.db_key} changed while this step ran; "
                "another run wrote it first. Nothing was pushed."
            ) from error
        raise
    log(f"pushed s3://{settings.data_bucket}/{settings.db_key}")


def push_dir(s3: Any, bucket: str, local: Path, prefix: str) -> None:
    """Upload every file under `local` to `<prefix>/` with its relative path. Existing keys are replaced."""
    if not local.is_dir():
        raise FileNotFoundError(f"{local} is not a directory; nothing to push")
    count = 0
    for path in sorted(p for p in local.rglob("*") if p.is_file()):
        key = f"{prefix}/{path.relative_to(local).as_posix()}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type})
        count += 1
    log(f"pushed {count} files from {local} to s3://{bucket}/{prefix}/")


def parse_push_dir(value: str) -> tuple[Path, str]:
    local, sep, prefix = value.partition("=")
    if not (sep and local and prefix.strip("/")):
        raise argparse.ArgumentTypeError(f"expected LOCAL_DIR=PREFIX, got {value!r}")
    return Path(local), prefix.strip("/")


def log(message: str) -> None:
    print(f"quack-run: {message}", file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None, s3: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pull-db", action="store_true", help="download the database before running"
    )
    parser.add_argument(
        "--push-db",
        action="store_true",
        help="upload the database if the command succeeds",
    )
    parser.add_argument(
        "--push-dir",
        action="append",
        default=[],
        type=parse_push_dir,
        metavar="LOCAL_DIR=PREFIX",
        help="upload a folder to <project>/<PREFIX>/ in the artifacts bucket if the command succeeds",
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="the command to run, after --"
    )
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given; put it after --")
    if args.push_db and not args.pull_db:
        parser.error(
            "--push-db needs --pull-db: the push is conditional on the version pulled"
        )

    settings = Settings.from_env()
    if args.push_dir and not settings.artifacts_bucket:
        parser.error("--push-dir needs QUACK_ARTIFACTS_BUCKET")
    s3 = s3 or boto3.client("s3")

    etag = pull_db(s3, settings) if args.pull_db else None
    log(f"running: {' '.join(command)}")
    returncode = subprocess.run(command, check=False).returncode
    if returncode != 0:
        log(f"command exited with {returncode}; nothing pushed")
        return returncode

    if args.push_db:
        push_db(s3, settings, etag)
    for local, prefix in args.push_dir:
        assert settings.artifacts_bucket  # checked before the command ran
        push_dir(s3, settings.artifacts_bucket, local, f"{settings.project}/{prefix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
