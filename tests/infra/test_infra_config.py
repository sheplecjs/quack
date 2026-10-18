import pytest
from pydantic import ValidationError

from quack.config import load_config

SCHEDULE = "cron(0 7 ? * MON-FRI *)"
BASE = {
    "github_repo": "sheplecjs/quack",
    "github_owner_id": 63471359,
    "github_repo_id": 1393700582,
    "projects": {"financial": {"schedule": SCHEDULE}},
}


def make(**overrides):
    return load_config({**BASE, **overrides})


def test_accepts_the_minimal_config():
    config = make()
    assert config.projects["financial"].secret_keys == ()
    assert config.log_retention_days == 30


def test_accepts_json_from_the_command_line():
    assert load_config(
        '{"github_repo": "a/b", "github_owner_id": 1, "github_repo_id": 2,'
        ' "projects": {"web": {"schedule": "cron(0 1 * * ? *)"}}}'
    )


@pytest.mark.parametrize("schedule", ["rate(1 day)", "0 7 * * *", "cron(0 7 * * *)"])
def test_rejects_schedules_that_arent_six_field_cron(schedule):
    with pytest.raises(ValidationError, match="cron"):
        make(projects={"financial": {"schedule": schedule}})


def test_rejects_secret_keys_dlt_wont_read():
    with pytest.raises(ValidationError, match="SOURCES__"):
        make(
            projects={
                "financial": {
                    "schedule": SCHEDULE,
                    "secret_keys": ["API_KEY"],
                }
            }
        )


@pytest.mark.parametrize(
    "projects", [{}, {"Financial": {"schedule": "cron(0 7 ? * MON-FRI *)"}}]
)
def test_rejects_missing_or_badly_named_projects(projects):
    with pytest.raises(ValidationError):
        make(projects=projects)


def test_rejects_retention_cloudwatch_doesnt_offer():
    with pytest.raises(ValidationError):
        make(log_retention_days=31)


def test_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        make(github_repository="typo/quack")


def test_requires_the_context():
    with pytest.raises(ValueError, match="no `quack` context"):
        load_config(None)


def test_subject_names_the_repository_by_name_and_id():
    assert make().github_subject_repo == "sheplecjs@63471359/quack@1393700582"


@pytest.mark.parametrize("missing", ["github_owner_id", "github_repo_id"])
def test_requires_the_github_ids(missing):
    with pytest.raises(ValidationError, match=missing):
        load_config({k: v for k, v in BASE.items() if k != missing})
