import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk import aws_iam as iam
from aws_cdk.assertions import Match, Template

from quack.app import GITHUB_OIDC_STACK, PIPELINE_STACK, STORAGE_STACK, build
from quack.config import load_config

CDK_JSON = Path(__file__).resolve().parents[2] / "cdk.json"
CONTEXT = json.loads(CDK_JSON.read_text())["context"]
ENV = cdk.Environment(account="123456789012", region="us-east-1")


@pytest.fixture(scope="module")
def stacks(tmp_path_factory):
    app = cdk.App(context=CONTEXT, outdir=str(tmp_path_factory.mktemp("cdk.out")))
    stacks = build(app, load_config(CONTEXT["quack"]), ENV)
    # Runs cdk-nag; raises if any finding isn't acknowledged
    app.synth()
    return {name: Template.from_stack(stack) for name, stack in stacks.items()}


def test_synth_passes_cdk_nag(stacks):
    assert set(stacks) == {GITHUB_OIDC_STACK, STORAGE_STACK, PIPELINE_STACK}


def test_an_unacknowledged_finding_fails_synth(tmp_path):
    app = cdk.App(context=CONTEXT, outdir=str(tmp_path))
    build(app, load_config(CONTEXT["quack"]), ENV)
    stack = cdk.Stack(app, "Extra", env=ENV)
    iam.User(stack, "Wildcard").add_to_policy(
        iam.PolicyStatement(actions=["s3:*"], resources=["*"])
    )
    with pytest.raises(Exception, match="AwsSolutions-IAM"):
        app.synth()


def test_storage_buckets_are_private_encrypted_and_retained(stacks):
    storage = stacks[STORAGE_STACK]
    storage.resource_count_is("AWS::S3::Bucket", 3)
    buckets = storage.find_resources("AWS::S3::Bucket")
    for bucket in buckets.values():
        assert bucket["DeletionPolicy"] == "Retain"
        props = bucket["Properties"]
        assert props["PublicAccessBlockConfiguration"] == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }
        assert props["BucketEncryption"]["ServerSideEncryptionConfiguration"]
    # TLS only on every bucket
    for policy in storage.find_resources("AWS::S3::BucketPolicy").values():
        statements = policy["Properties"]["PolicyDocument"]["Statement"]
        assert any(
            s["Effect"] == "Deny"
            and s["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
            for s in statements
        )


def test_data_bucket_is_versioned_with_noncurrent_expiry(stacks):
    stacks[STORAGE_STACK].has_resource_properties(
        "AWS::S3::Bucket",
        {
            "VersioningConfiguration": {"Status": "Enabled"},
            "LifecycleConfiguration": {
                "Rules": Match.array_with(
                    [
                        Match.object_like(
                            {"NoncurrentVersionExpiration": {"NoncurrentDays": 30}}
                        )
                    ]
                )
            },
        },
    )


def test_secrets_hold_only_placeholders(stacks):
    secrets = stacks[STORAGE_STACK].find_resources("AWS::SecretsManager::Secret")
    assert len(secrets) == 2
    for secret in secrets.values():
        values = json.loads(secret["Properties"]["SecretString"])
        assert set(values.values()) == {"<set-me>"}


def test_ephemeral_stack_owns_no_data(stacks):
    pipeline = stacks[PIPELINE_STACK]
    for kind in (
        "AWS::S3::Bucket",
        "AWS::SecretsManager::Secret",
        "AWS::SNS::Topic",
        "AWS::KMS::Key",
    ):
        pipeline.resource_count_is(kind, 0)
    # Storage reaches it through SSM parameters, not CloudFormation exports
    parameters = pipeline.to_json()["Parameters"]
    assert any(
        p["Default"] == "/quack/storage/data-bucket-name" for p in parameters.values()
    )
    assert "Fn::ImportValue" not in json.dumps(pipeline.to_json())


def test_tasks_run_in_private_subnets_without_public_ips(stacks):
    pipeline = stacks[PIPELINE_STACK]
    pipeline.resource_count_is("AWS::EC2::NatGateway", 1)
    pipeline.has_resource_properties(
        "AWS::EC2::VPCEndpoint", {"VpcEndpointType": "Gateway"}
    )
    pipeline.resource_count_is("AWS::EC2::FlowLog", 1)
    for machine in pipeline.find_resources("AWS::StepFunctions::StateMachine").values():
        definition = json.dumps(machine["Properties"]["DefinitionString"])
        assert '\\"AssignPublicIp\\":\\"ENABLED\\"' not in definition
        assert "privateSubnet" in definition


def test_only_web_opens_postgres(stacks):
    groups = stacks[PIPELINE_STACK].find_resources("AWS::EC2::SecurityGroup")
    ports = {
        name: sorted(
            rule["FromPort"] for rule in group["Properties"]["SecurityGroupEgress"]
        )
        for name, group in groups.items()
        if "Pipeline" in name
    }
    assert sorted(ports.values()) == [[443], [443, 5432]]


def test_task_role_is_scoped_to_its_project_prefix(stacks):
    policies = stacks[PIPELINE_STACK].find_resources("AWS::IAM::Policy")
    financial = next(
        p
        for name, p in policies.items()
        if name.startswith("FinancialPipelineTaskTaskRole")
    )
    document = json.dumps(financial["Properties"]["PolicyDocument"])
    assert "/financial/*" in document
    assert "/web/" not in document
    assert "s3:DeleteObject" not in document


def test_each_state_machine_runs_load_build_render(stacks):
    machines = stacks[PIPELINE_STACK].find_resources("AWS::StepFunctions::StateMachine")
    assert len(machines) == 2
    for machine in machines.values():
        props = machine["Properties"]
        definition = "".join(
            p for p in props["DefinitionString"]["Fn::Join"][1] if isinstance(p, str)
        )
        states = json.loads(definition)["States"]
        assert [
            states["Load"]["Next"],
            states["Build"]["Next"],
            states["Render"]["Next"],
        ] == [
            "Build",
            "Render",
            "Done",
        ]
        assert props["TracingConfiguration"] == {"Enabled": True}
        assert props["LoggingConfiguration"]["Level"] == "ALL"


def test_schedules_start_the_state_machines(stacks):
    pipeline = stacks[PIPELINE_STACK]
    schedules = pipeline.find_resources("AWS::Scheduler::Schedule")
    assert {s["Properties"]["ScheduleExpression"] for s in schedules.values()} == {
        "cron(0 9 ? * MON-FRI *)",
        "cron(30 9 ? * MON-FRI *)",
    }
    for schedule in schedules.values():
        assert schedule["Properties"]["Target"]["Arn"]["Ref"].endswith(
            tuple(pipeline.find_resources("AWS::StepFunctions::StateMachine"))
        )


def test_failures_alert_through_the_persistent_topic(stacks):
    stacks[PIPELINE_STACK].has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": Match.object_like(
                {
                    "source": ["aws.states"],
                    "detail": Match.object_like(
                        {"status": ["FAILED", "TIMED_OUT", "ABORTED"]}
                    ),
                }
            )
        },
    )


def test_github_roles_trust_exactly_this_repository(stacks):
    roles = stacks[GITHUB_OIDC_STACK].find_resources("AWS::IAM::Role")
    subjects = set()
    for role in roles.values():
        [statement] = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        condition = statement["Condition"]["StringEquals"]
        assert (
            condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
        )
        subjects.add(condition["token.actions.githubusercontent.com:sub"])
        assert "StringLike" not in statement["Condition"]
    assert subjects == {
        "repo:sheplecjs/quack:environment:aws",
        "repo:sheplecjs/quack:pull_request",
    }


def test_github_roles_can_only_assume_cdk_bootstrap_roles(stacks):
    for policy in stacks[GITHUB_OIDC_STACK].find_resources("AWS::IAM::Policy").values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
            resources = (
                statement["Resource"]
                if isinstance(statement["Resource"], list)
                else [statement["Resource"]]
            )
            assert resources and all(isinstance(r, str) for r in resources)
            assert all(
                r in {bootstrap_role(kind) for kind in BOOTSTRAP_ROLE_KINDS}
                for r in resources
            )


# The roles `cdk bootstrap` creates, by the names it gives them
BOOTSTRAP_ROLE_KINDS = ("deploy", "file-publishing", "image-publishing", "lookup")


def bootstrap_role(kind):
    return (
        f"arn:aws:iam::{ENV.account}:role/"
        f"cdk-hnb659fds-{kind}-role-{ENV.account}-{ENV.region}"
    )


def test_deploy_role_can_assume_every_bootstrap_role_and_diff_role_only_lookup(stacks):
    policies = stacks[GITHUB_OIDC_STACK].find_resources("AWS::IAM::Policy")

    def assumable(prefix):
        [statement] = next(
            p for name, p in policies.items() if name.startswith(prefix)
        )["Properties"]["PolicyDocument"]["Statement"]
        resource = statement["Resource"]
        return set(resource if isinstance(resource, list) else [resource])

    assert assumable("GithubDeployRole") == {
        bootstrap_role(k) for k in BOOTSTRAP_ROLE_KINDS
    }
    assert assumable("GithubDiffRole") == {bootstrap_role("lookup")}


def test_diff_role_is_read_only(stacks):
    policies = stacks[GITHUB_OIDC_STACK].find_resources("AWS::IAM::Policy")
    diff = next(p for name, p in policies.items() if name.startswith("GithubDiffRole"))
    assert "lookup" in json.dumps(diff) and "deploy" not in json.dumps(diff)


def test_persistent_stacks_have_termination_protection():
    app = cdk.App(context=CONTEXT)
    stacks = build(app, load_config(CONTEXT["quack"]), ENV)
    assert stacks[STORAGE_STACK].termination_protection
    assert stacks[GITHUB_OIDC_STACK].termination_protection
    assert not stacks[PIPELINE_STACK].termination_protection


def test_flow_logs_go_to_the_logs_bucket_as_partitioned_parquet(stacks):
    pipeline = stacks[PIPELINE_STACK]
    pipeline.has_resource_properties(
        "AWS::EC2::FlowLog",
        {
            "LogDestinationType": "s3",
            "DestinationOptions": {
                "fileFormat": "parquet",
                "hiveCompatiblePartitions": True,
                "perHourPartition": True,
            },
        },
    )
    [flow_log] = pipeline.find_resources("AWS::EC2::FlowLog").values()
    destination = json.dumps(flow_log["Properties"]["LogDestination"])
    assert "logsbucketname" in destination and "/vpc-flow-logs/" in destination


def test_logs_bucket_policy_allows_flow_log_delivery_from_this_account_only(stacks):
    policies = stacks[STORAGE_STACK].find_resources("AWS::S3::BucketPolicy")
    statements = {
        statement.get("Sid"): statement
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    }
    write = statements["AWSLogDeliveryWrite"]
    assert write["Principal"] == {"Service": "delivery.logs.amazonaws.com"}
    assert write["Condition"]["StringEquals"]["aws:SourceAccount"] == ENV.account
    assert "/vpc-flow-logs/AWSLogs/" in json.dumps(write["Resource"])
    assert statements["AWSLogDeliveryAclCheck"]["Condition"]["StringEquals"]
