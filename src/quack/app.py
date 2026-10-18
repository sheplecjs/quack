import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from quack.config import QuackConfig, load_config
from quack.stacks.github_oidc import GithubOidcStack
from quack.stacks.pipeline import PipelineStack
from quack.stacks.storage import StorageStack

GITHUB_OIDC_STACK = "QuackGithubOidc"
STORAGE_STACK = "QuackStorage"
PIPELINE_STACK = "QuackPipeline"


def build(
    app: cdk.App, config: QuackConfig, env: cdk.Environment | None = None
) -> dict[str, cdk.Stack]:
    oidc = GithubOidcStack(app, GITHUB_OIDC_STACK, config=config, env=env)
    storage = StorageStack(app, STORAGE_STACK, config=config, env=env)
    pipeline = PipelineStack(app, PIPELINE_STACK, config=config, env=env)
    pipeline.add_stack_dependency(
        storage, reason="Reads bucket, secret and topic identifiers from SSM"
    )

    cdk.Tags.of(app).add("quack:repository", config.github_repo)
    cdk.Tags.of(oidc).add("quack:lifecycle", "persistent")
    cdk.Tags.of(storage).add("quack:lifecycle", "persistent")
    cdk.Tags.of(pipeline).add("quack:lifecycle", "ephemeral")
    cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app))
    return {GITHUB_OIDC_STACK: oidc, STORAGE_STACK: storage, PIPELINE_STACK: pipeline}


def main() -> None:
    app = cdk.App()
    env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    )
    build(app, load_config(app.node.try_get_context("quack")), env)
    app.synth()


if __name__ == "__main__":
    main()
