from dataclasses import dataclass
from pathlib import Path

from aws_cdk import Annotations, Duration, IgnoreMode, RemovalPolicy, Stack, TimeZone
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as events_targets
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_scheduler_targets as scheduler_targets
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from quack.config import ProjectConfig
from quack.nag import IAM5, acknowledge, wildcard_resource, wildcard_resources_in

# The repository root: the image's build context
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = "/data"
DBT_BUILD = (
    "dbt build && dbt docs generate --static"
    f" && mkdir -p {DATA_DIR}/report && cp {DATA_DIR}/target/static_index.html {DATA_DIR}/report/dbt_docs.html"
)


@dataclass(frozen=True)
class SharedStorage:
    """The persistent stack's resources, as the pipeline stack imports them."""

    logs_bucket: s3.IBucket
    data_bucket: s3.IBucket
    artifacts_bucket: s3.IBucket
    alert_topic: sns.ITopic
    secrets: dict[str, secretsmanager.ISecret]


def step_commands(project: str) -> dict[str, list[str]]:
    """Each step's container command. Every step pulls the database; only load and build change it."""
    return {
        "Load": ["quack-run", "--pull-db", "--push-db", "--", f"{project}-load", "all"],
        "Build": [
            "quack-run",
            "--pull-db",
            "--push-db",
            "--push-dir",
            f"{DATA_DIR}/target=dbt",
            "--push-dir",
            f"{DATA_DIR}/report=report",
            "--",
            "bash",
            "-c",
            DBT_BUILD,
        ],
        "Render": [
            "quack-run",
            "--pull-db",
            "--push-dir",
            f"{DATA_DIR}/report=report",
            "--",
            "bash",
            "render_reports.sh",
            f"{DATA_DIR}/report",
        ],
    }


class ProjectPipeline(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        project: str,
        settings: ProjectConfig,
        cluster: ecs.ICluster,
        storage: SharedStorage,
        time_zone: TimeZone,
        log_retention: logs.RetentionDays,
    ) -> None:
        super().__init__(scope, id)

        log_group = logs.LogGroup(
            self, "Logs", retention=log_retention, removal_policy=RemovalPolicy.DESTROY
        )

        task_definition = ecs.FargateTaskDefinition(
            self,
            "Task",
            cpu=settings.cpu,
            memory_limit_mib=settings.memory_mib,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        secret = storage.secrets[project]
        container = task_definition.add_container(
            "Step",
            image=ecs.ContainerImage.from_asset(
                str(REPO_ROOT),
                file="Dockerfile",
                build_args={"PROJECT": project},
                platform=ecr_assets.Platform.LINUX_AMD64,
                ignore_mode=IgnoreMode.DOCKER,
            ),
            logging=ecs.LogDriver.aws_logs(stream_prefix=project, log_group=log_group),
            environment={
                "QUACK_DATA_BUCKET": storage.data_bucket.bucket_name,
                "QUACK_ARTIFACTS_BUCKET": storage.artifacts_bucket.bucket_name,
            },
            secrets={
                key: ecs.Secret.from_secrets_manager(secret, field=key)
                for key in settings.secret_keys
            },
        )

        prefix = f"{project}/*"
        storage.data_bucket.grant_read(task_definition.task_role, prefix)
        storage.data_bucket.grant_put(task_definition.task_role, prefix)
        storage.artifacts_bucket.grant_put(task_definition.task_role, prefix)

        security_group = ec2.SecurityGroup(
            self,
            "Tasks",
            vpc=cluster.vpc,
            description=f"{project} pipeline tasks: outbound only",
            allow_all_outbound=False,
        )
        for port in (443, *settings.extra_egress_ports):
            security_group.add_egress_rule(
                ec2.Peer.any_ipv4(), ec2.Port.tcp(port), f"Outbound TCP {port}"
            )

        failed = sfn.Fail(
            self, "Failed", comment="A step failed; S3 keeps the last successful push"
        )
        steps = [
            self._step(
                name,
                command,
                cluster,
                task_definition,
                container,
                security_group,
                settings,
            )
            for name, command in step_commands(project).items()
        ]
        for step in steps:
            step.add_catch(failed)
        chain = sfn.Chain.start(steps[0])
        for step in steps[1:]:
            chain = chain.next(step)

        self.state_machine = sfn.StateMachine(
            self,
            "StateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(
                chain.next(sfn.Succeed(self, "Done"))
            ),
            timeout=Duration.minutes(settings.step_timeout_minutes * len(steps) + 30),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(
                    self,
                    "StateMachineLogs",
                    retention=log_retention,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
                level=sfn.LogLevel.ALL,
                include_execution_data=True,
            ),
        )

        scheduler.Schedule(
            self,
            "Schedule",
            description=f"Runs the {project} pipeline",
            schedule=scheduler.ScheduleExpression.expression(
                settings.schedule, time_zone
            ),
            target=scheduler_targets.StepFunctionsStartExecution(  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
                self.state_machine,
                input=scheduler.ScheduleTargetInput.from_object(
                    {"trigger": "schedule"}
                ),
                retry_attempts=0,
            ),
        )

        on_failure = events.Rule(
            self,
            "OnFailure",
            description=f"Alerts when a {project} pipeline run doesn't succeed",
            event_pattern=events.EventPattern(
                source=["aws.states"],
                detail_type=["Step Functions Execution Status Change"],
                detail={
                    "status": ["FAILED", "TIMED_OUT", "ABORTED"],
                    "stateMachineArn": [self.state_machine.state_machine_arn],
                },
            ),
            targets=[events_targets.SnsTopic(storage.alert_topic)],  # ty: ignore[invalid-argument-type]  (jsii protocol, see nag.py)
        )

        Annotations.of(on_failure).acknowledge_warning(
            "@aws-cdk/aws-events:ruleUnresolvedEnvironment",
            "Same account and region by construction",
        )
        self._acknowledge(project, task_definition, storage)

    def _step(
        self,
        name: str,
        command: list[str],
        cluster: ecs.ICluster,
        task_definition: ecs.FargateTaskDefinition,
        container: ecs.ContainerDefinition,
        security_group: ec2.ISecurityGroup,
        settings: ProjectConfig,
    ) -> tasks.EcsRunTask:
        step = tasks.EcsRunTask(
            self,
            name,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
            cluster=cluster,
            task_definition=task_definition,
            launch_target=tasks.EcsFargateLaunchTarget(
                platform_version=ecs.FargatePlatformVersion.LATEST
            ),
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
            assign_public_ip=False,
            container_overrides=[
                tasks.ContainerOverride(container_definition=container, command=command)
            ],
            task_timeout=sfn.Timeout.duration(
                Duration.minutes(settings.step_timeout_minutes)
            ),
            result_path=sfn.JsonPath.DISCARD,
        )
        step.add_retry(
            errors=["ECS.AmazonECSException"],
            interval=Duration.seconds(30),
            max_attempts=3,
            backoff_rate=2,
        )
        return step

    def _acknowledge(
        self,
        project: str,
        task_definition: ecs.FargateTaskDefinition,
        storage: SharedStorage,
    ) -> None:
        acknowledge(
            task_definition,
            "Environment variables carry only bucket names; secrets are injected from Secrets Manager",
            "AwsSolutions-ECS2",
        )
        prefix = f"{project}/*"
        acknowledge(
            task_definition.task_role,
            "Object access is limited to the project's own key prefix; the action wildcards are CDK's "
            "grant_read / grant_put sets",
            wildcard_resource(self, storage.data_bucket.arn_for_objects(prefix)),
            wildcard_resource(self, storage.artifacts_bucket.arn_for_objects(prefix)),
            *(
                f"{IAM5}[Action::s3:{action}]"
                for action in ("Abort*", "GetBucket*", "GetObject*", "List*")
            ),
        )
        acknowledge(
            task_definition.obtain_execution_role(),
            "ecr:GetAuthorizationToken has no resource-level permissions",
            f"{IAM5}[Resource::*]",
        )
        task_family = Stack.of(self).resolve(task_definition.task_definition_arn)["Ref"]
        acknowledge(
            self.state_machine.role,
            "ecs:RunTask on every revision of this project's task family, and X-Ray and CloudWatch Logs "
            "delivery, which have no resource-level permissions",
            f"{IAM5}[Resource::*]",
            *wildcard_resources_in(self.state_machine.role, containing=task_family),
        )
