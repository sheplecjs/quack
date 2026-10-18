from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from quack.config import QuackConfig

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
# The audience aws-actions/configure-aws-credentials requests
AUDIENCE = "sts.amazonaws.com"


class GithubOidcStack(Stack):
    def __init__(
        self, scope: Construct, id: str, *, config: QuackConfig, **kwargs
    ) -> None:
        super().__init__(scope, id, termination_protection=True, **kwargs)

        if config.github_oidc_provider_arn:
            provider = iam.OidcProviderNative.from_oidc_provider_arn(
                self, "GithubProvider", config.github_oidc_provider_arn
            )
        else:
            provider = iam.OidcProviderNative(
                self, "GithubProvider", url=GITHUB_OIDC_URL, client_ids=[AUDIENCE]
            )

        def bootstrap_role(kind: str) -> str:
            return (
                f"arn:{self.partition}:iam::{self.account}:role/"
                f"cdk-{config.cdk_qualifier}-{kind}-role-{self.account}-{self.region}"
            )

        self.deploy_role = self._role(
            "GithubDeployRole",
            provider,
            subject=f"repo:{config.github_repo}:environment:{config.github_environment}",
            description=f"GitHub Actions deploys from {config.github_repo} ({config.github_environment} environment)",
            assumable=[
                bootstrap_role(kind)
                for kind in ("deploy", "file-publishing", "image-publishing", "lookup")
            ],
        )
        self.diff_role = self._role(
            "GithubDiffRole",
            provider,
            subject=f"repo:{config.github_repo}:pull_request",
            description=f"GitHub Actions read-only diffs for pull requests in {config.github_repo}",
            assumable=[bootstrap_role("lookup")],
        )
        CfnOutput(self, "DeployRoleArn", value=self.deploy_role.role_arn)
        CfnOutput(self, "DiffRoleArn", value=self.diff_role.role_arn)

    def _role(
        self,
        id: str,
        provider: iam.IOidcProvider,
        *,
        subject: str,
        description: str,
        assumable: list[str],
    ) -> iam.Role:
        role = iam.Role(
            self,
            id,
            description=description,
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {
                        f"{GITHUB_OIDC_HOST}:aud": AUDIENCE,
                        f"{GITHUB_OIDC_HOST}:sub": subject,
                    }
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(actions=["sts:AssumeRoleWithWebIdentity"], resources=assumable)
        )
        return role
