import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CRON_PATTERN = re.compile(r"^cron\((\S+ ){5}\S+\)$")
SECRET_KEY_PATTERN = re.compile(r"^SOURCES__[A-Z0-9_]+__[A-Z0-9_]+$")
DEFAULT_QUALIFIER = "hnb659fds"

Port = Annotated[int, Field(ge=1, le=65535)]


class ProjectConfig(BaseModel):
    """One analytics project under projects/, run as load → build → render."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule: str
    secret_keys: tuple[str, ...] = ()
    extra_egress_ports: tuple[Port, ...] = ()
    cpu: int = 1024
    memory_mib: int = 4096
    step_timeout_minutes: int = Field(default=60, ge=1)

    @field_validator("schedule")
    @classmethod
    def _check_schedule(cls, value: str) -> str:
        if not CRON_PATTERN.match(value):
            raise ValueError(
                f"schedule must be a six-field EventBridge cron(...), got {value!r}"
            )
        return value

    @field_validator("secret_keys")
    @classmethod
    def _check_secret_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        bad = [key for key in value if not SECRET_KEY_PATTERN.match(key)]
        if bad:
            raise ValueError(
                f"secret keys must be dlt env var names (SOURCES__<SOURCE>__<KEY>): {bad}"
            )
        return value


class QuackConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    github_repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    # GitHub's numeric ids for the owner and repository, which its OIDC subjects now carry
    # (repo:<owner>@<owner_id>/<name>@<repo_id>:...). A repository deleted and recreated under the
    # same name gets a new id, so it can't assume the roles. Both are public: GET /repos/<owner>/<name>
    # returns them as owner.id and id.
    github_owner_id: int = Field(gt=0)
    github_repo_id: int = Field(gt=0)
    github_environment: str = "aws"
    github_oidc_provider_arn: str | None = None
    cdk_qualifier: str = DEFAULT_QUALIFIER
    schedule_time_zone: str = "UTC"
    alert_email: str | None = None
    log_retention_days: Literal[1, 3, 5, 7, 14, 30, 60, 90, 180, 365] = 30
    noncurrent_version_days: int = Field(default=30, ge=1)
    projects: dict[str, ProjectConfig]

    @property
    def github_subject_repo(self) -> str:
        """The repository as GitHub's OIDC subject names it: <owner>@<owner_id>/<name>@<repo_id>."""
        owner, name = self.github_repo.split("/")
        return f"{owner}@{self.github_owner_id}/{name}@{self.github_repo_id}"

    @field_validator("projects")
    @classmethod
    def _check_projects(
        cls, value: dict[str, ProjectConfig]
    ) -> dict[str, ProjectConfig]:
        if not value:
            raise ValueError("at least one project is required")
        bad = [name for name in value if not re.fullmatch(r"[a-z][a-z0-9]*", name)]
        if bad:
            raise ValueError(
                f"project names must be lower-case letters and digits: {bad}"
            )
        return value


def load_config(context: Any) -> QuackConfig:
    """Validate the `quack` context value (a dict from cdk.json, or JSON passed with -c)."""
    if context is None:
        raise ValueError("cdk.json has no `quack` context")
    if isinstance(context, str):
        return QuackConfig.model_validate_json(context)
    return QuackConfig.model_validate(context)
