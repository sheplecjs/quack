from aws_cdk import Stack, TimeZone
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from quack.config import QuackConfig
from quack.stacks import storage
from quack.stacks.project_pipeline import ProjectPipeline, SharedStorage

# The retention periods CloudWatch Logs accepts, by days
RETENTION_DAYS = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    60: logs.RetentionDays.TWO_MONTHS,
    90: logs.RetentionDays.THREE_MONTHS,
    180: logs.RetentionDays.SIX_MONTHS,
    365: logs.RetentionDays.ONE_YEAR,
}


class PipelineStack(Stack):
    def __init__(
        self, scope: Construct, id: str, *, config: QuackConfig, **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)
        retention = RETENTION_DAYS[config.log_retention_days]

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
            gateway_endpoints={
                "S3": ec2.GatewayVpcEndpointOptions(
                    service=ec2.GatewayVpcEndpointAwsService.S3
                )
            },
        )
        shared = self._import_storage(config)

        self.vpc.add_flow_log(
            "FlowLog",
            destination=ec2.FlowLogDestination.to_s3(
                shared.logs_bucket,
                f"{storage.FLOW_LOGS_PREFIX}/",
                file_format=ec2.FlowLogFileFormat.PARQUET,
                hive_compatible_partitions=True,
                per_hour_partition=True,
            ),
        )

        cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=self.vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        self.pipelines = {
            project: ProjectPipeline(
                self,
                f"{project.title()}Pipeline",
                project=project,
                settings=settings,
                cluster=cluster,
                storage=shared,
                time_zone=TimeZone.of(config.schedule_time_zone),
                log_retention=retention,
            )
            for project, settings in config.projects.items()
        }

    def _import_storage(self, config: QuackConfig) -> SharedStorage:
        """Resolved from SSM at deploy time, so this stack deploys only once the storage stack exists."""

        def parameter(name: str) -> str:
            return ssm.StringParameter.value_for_string_parameter(self, name)

        return SharedStorage(
            logs_bucket=s3.Bucket.from_bucket_name(
                self, "LogsBucket", parameter(storage.logs_bucket_parameter())
            ),
            data_bucket=s3.Bucket.from_bucket_name(
                self, "DataBucket", parameter(storage.data_bucket_parameter())
            ),
            artifacts_bucket=s3.Bucket.from_bucket_name(
                self, "ArtifactsBucket", parameter(storage.artifacts_bucket_parameter())
            ),
            alert_topic=sns.Topic.from_topic_arn(
                self, "AlertTopic", parameter(storage.alert_topic_parameter())
            ),
            secrets={
                project: secretsmanager.Secret.from_secret_complete_arn(
                    self,
                    f"{project.title()}Secret",
                    parameter(storage.secret_parameter(project)),
                )
                for project in config.projects
            },
        )
