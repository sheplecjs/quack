"""Acknowledging cdk-nag findings: each with a reason, on the construct it's about.

A rule that reports several findings on one resource (IAM5's wildcards) needs each by its full id, e.g.
`AwsSolutions-IAM5[Resource::arn:aws:s3:::<BucketParameter>/web/*]`; there's no blanket acknowledgment.
The helpers here render those ids from the values themselves, so they stay correct when logical ids change.
"""

import json
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import IConstruct

IAM5 = "AwsSolutions-IAM5"

# A note for the `ty: ignore[invalid-argument-type]` comments in the stacks: jsii generates protocols
# (ITopic, IScheduleTarget, ...) whose method parameters are named differently from the classes that
# implement them, which ty reports as a mismatch. They are compatible; CDK checks them at runtime.


def acknowledge(construct: IConstruct, reason: str, *rule_ids: str) -> None:
    """Acknowledge findings on `construct` and its children."""
    cdk.Validations.of(construct).acknowledge(
        *(cdk.Acknowledgment(id=rule_id, reason=reason) for rule_id in rule_ids)
    )


def render(value: Any) -> str:
    """A resolved CloudFormation value as cdk-nag writes it in a finding id."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and len(value) == 1:
        [(function, args)] = value.items()
        if function == "Ref":
            return f"<{args}>"
        if function == "Fn::GetAtt":
            return f"<{'.'.join(args)}>"
        if function == "Fn::Join":
            separator, parts = args
            return separator.join(render(part) for part in parts)
    return json.dumps(value, separators=(",", ":"))


def wildcard_resource(scope: IConstruct, resource: str) -> str:
    """The IAM5 finding id for a wildcard resource, e.g. `bucket.arn_for_objects("web/*")`."""
    return f"{IAM5}[Resource::{render(cdk.Stack.of(scope).resolve(resource))}]"


def wildcard_resources_in(role: iam.IRole, containing: str) -> list[str]:
    """IAM5 finding ids for the wildcard resources in a role's default policy whose rendering contains
    `containing`. For grants CDK generates, where there's no value to pass to `wildcard_resource`."""
    policy = role.node.try_find_child("DefaultPolicy")
    if not isinstance(policy, iam.Policy):
        return []
    document = cdk.Stack.of(role).resolve(policy.document.to_json())
    found = []
    for statement in document.get("Statement", []):
        resources = statement.get("Resource", [])
        for resource in resources if isinstance(resources, list) else [resources]:
            rendered = render(resource)
            if "*" in rendered and containing in rendered:
                found.append(f"{IAM5}[Resource::{rendered}]")
    return found
