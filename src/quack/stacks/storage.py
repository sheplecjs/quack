from aws_cdk import Duration, RemovalPolicy, SecretValue, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from quack.config import QuackConfig
from quack.nag import acknowledge

SSM_PREFIX = "/quack/storage"
SECRET_PLACEHOLDER = "<set-me>"
# VPC flow logs land under <prefix>/AWSLogs/aws-account-id=.../aws-service=vpcflowlogs/aws-region=.../
# year=/month=/day=/hour=/ as Parquet, a layout Athena can query with partition projection
FLOW_LOGS_PREFIX = "vpc-flow-logs"


def logs_bucket_parameter() -> str:
    return f"{SSM_PREFIX}/logs-bucket-name"


def data_bucket_parameter() -> str:
    return f"{SSM_PREFIX}/data-bucket-name"


def artifacts_bucket_parameter() -> str:
    return f"{SSM_PREFIX}/artifacts-bucket-name"


def alert_topic_parameter() -> str:
    return f"{SSM_PREFIX}/alert-topic-arn"


def secret_parameter(project: str) -> str:
    return f"{SSM_PREFIX}/projects/{project}/secret-arn"


class StorageStack(Stack):
    def __init__(
        self, scope: Construct, id: str, *, config: QuackConfig, **kwargs
    ) -> None:
        super().__init__(scope, id, termination_protection=True, **kwargs)

        self.logs_bucket = s3.Bucket(
            self,
            "Logs",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(365))],
            removal_policy=RemovalPolicy.RETAIN,
        )
        acknowledge(
            self.logs_bucket,
            "This is the access log bucket; logging it to itself would loop",
            "AwsSolutions-S1",
        )
        self._allow_flow_log_delivery(self.logs_bucket)

        self.data_bucket = self._bucket(
            "Data",
            self.logs_bucket,
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(
                        config.noncurrent_version_days
                    ),
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                )
            ],
        )
        self.artifacts_bucket = self._bucket(
            "Artifacts",
            self.logs_bucket,
            lifecycle_rules=[
                s3.LifecycleRule(
                    abort_incomplete_multipart_upload_after=Duration.days(1)
                )
            ],
        )

        self.secrets = {
            project: self._project_secret(project, settings.secret_keys)
            for project, settings in config.projects.items()
        }
        self.alert_topic = self._alert_topic(config.alert_email)

        for name, value, parameter in [
            ("LogsBucketName", self.logs_bucket.bucket_name, logs_bucket_parameter()),
            ("DataBucketName", self.data_bucket.bucket_name, data_bucket_parameter()),
            (
                "ArtifactsBucketName",
                self.artifacts_bucket.bucket_name,
                artifacts_bucket_parameter(),
            ),
            ("AlertTopicArn", self.alert_topic.topic_arn, alert_topic_parameter()),
        ]:
            ssm.StringParameter(
                self, name, parameter_name=parameter, string_value=value
            )
        for project, secret in self.secrets.items():
            ssm.StringParameter(
                self,
                f"{project.title()}SecretArn",
                parameter_name=secret_parameter(project),
                string_value=secret.secret_arn,
            )

    def _allow_flow_log_delivery(self, bucket: s3.Bucket) -> None:
        """The bucket policy VPC flow log delivery needs, declared here so CloudFormation owns it.

        Without it, creating a flow log adds these statements itself, and the next deploy of this stack
        would overwrite them.
        """
        delivery = iam.ServicePrincipal("delivery.logs.amazonaws.com")
        source = {
            "StringEquals": {"aws:SourceAccount": self.account},
            "ArnLike": {
                "aws:SourceArn": f"arn:{self.partition}:logs:{self.region}:{self.account}:*"
            },
        }
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AWSLogDeliveryWrite",
                principals=[delivery],  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
                actions=["s3:PutObject"],
                resources=[
                    bucket.arn_for_objects(
                        f"{FLOW_LOGS_PREFIX}/AWSLogs/{self.account}/*"
                    )
                ],
                conditions={
                    **source,
                    "StringEquals": {
                        **source["StringEquals"],
                        "s3:x-amz-acl": "bucket-owner-full-control",
                    },
                },
            )
        )
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AWSLogDeliveryAclCheck",
                principals=[delivery],  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
                actions=["s3:GetBucketAcl", "s3:ListBucket"],
                resources=[bucket.bucket_arn],
                conditions=source,
            )
        )

    def _bucket(self, id: str, access_logs: s3.IBucket, **kwargs) -> s3.Bucket:
        return s3.Bucket(
            self,
            id,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            server_access_logs_bucket=access_logs,
            server_access_logs_prefix=f"{id.lower()}/",
            removal_policy=RemovalPolicy.RETAIN,
            **kwargs,
        )

    def _project_secret(
        self, project: str, keys: tuple[str, ...]
    ) -> secretsmanager.Secret:
        """A JSON secret with one placeholder per key. Real values are set out of band, never in code."""
        secret = secretsmanager.Secret(
            self,
            f"{project.title()}Secret",
            description=f"dlt secrets for the {project} project, one key per environment variable",
            secret_object_value={
                key: SecretValue.unsafe_plain_text(SECRET_PLACEHOLDER) for key in keys
            },
            removal_policy=RemovalPolicy.RETAIN,
        )
        acknowledge(
            secret,
            "Third-party API keys and a read-only database login, issued outside AWS; there is no "
            "rotation function that could reissue them",
            "AwsSolutions-SMG4",
        )
        return secret

    def _alert_topic(self, email: str | None) -> sns.Topic:
        """Pipeline failure alerts. Persistent, so a subscription is confirmed once, not after every deploy."""
        key = kms.Key(
            self,
            "AlertKey",
            description="Encrypts the quack pipeline alert topic",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        topic = sns.Topic(self, "Alerts", master_key=key, enforce_ssl=True)  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
        # EventBridge publishes the failure events; an encrypted topic needs it to use the key too
        events = iam.ServicePrincipal("events.amazonaws.com")
        topic.grant_publish(events)
        key.grant(events, "kms:Decrypt", "kms:GenerateDataKey*")
        if email:
            topic.add_subscription(subscriptions.EmailSubscription(email))  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
        return topic
