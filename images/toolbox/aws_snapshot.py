"""Print the AWS account's state as JSON: {kind: {id: object}}, for the grader's `aws_unchanged` check.

Runs inside the toolbox (boto3 reads AWS_ENDPOINT_URL and the region from the environment). Every object gets
a "label" a task can name: its Name tag, else its name (group, role, bucket...), else its id.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2")
iam = boto3.client("iam")
s3 = boto3.client("s3")


def tag_name(obj: dict[str, Any]) -> str | None:
    return next((t["Value"] for t in obj.get("Tags") or [] if t["Key"] == "Name"), None)


def pages(client: Any, op: str, key: str, **kwargs: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in client.get_paginator(op).paginate(**kwargs):
        out += page.get(key, [])
    return out


def keyed(objects: list[dict[str, Any]], id_key: str, name_key: str | None = None) -> dict[str, Any]:
    out = {}
    for obj in objects:
        label = tag_name(obj) or (obj.get(name_key) if name_key else None) or obj[id_key]
        obj.pop("AvailableIpAddressCount", None)  # a subnet's counter: goes down when an instance starts
        out[str(obj[id_key])] = {**obj, "label": str(label)}
    return out


def optional(call: Any, **kwargs: Any) -> Any:
    """A bucket setting that may not exist (no policy, no encryption...): None then."""
    try:
        reply = call(**kwargs)
    except ClientError:
        return None
    reply.pop("ResponseMetadata", None)
    return reply


def roles() -> dict[str, Any]:
    out = {}
    for role in pages(iam, "list_roles", "Roles"):
        name = role["RoleName"]
        role.pop("RoleLastUsed", None)
        role["InlinePolicies"] = {
            p: iam.get_role_policy(RoleName=name, PolicyName=p)["PolicyDocument"]
            for p in sorted(iam.list_role_policies(RoleName=name)["PolicyNames"])
        }
        role["AttachedPolicies"] = sorted(
            p["PolicyArn"] for p in iam.list_attached_role_policies(RoleName=name)["AttachedPolicies"]
        )
        out[name] = {**role, "label": name}
    return out


def policies() -> dict[str, Any]:
    out = {}
    for pol in pages(iam, "list_policies", "Policies", Scope="Local"):
        version = iam.get_policy_version(PolicyArn=pol["Arn"], VersionId=pol["DefaultVersionId"])
        pol.pop("AttachmentCount", None)  # goes up when a role attaches it: tracked on the role
        pol["Document"] = version["PolicyVersion"]["Document"]
        out[pol["PolicyName"]] = {**pol, "label": pol["PolicyName"]}
    return out


def buckets() -> dict[str, Any]:
    out = {}
    for bucket in s3.list_buckets()["Buckets"]:
        name = bucket["Name"]
        out[name] = {
            "label": name,
            "Versioning": s3.get_bucket_versioning(Bucket=name).get("Status"),
            "PublicAccessBlock": optional(s3.get_public_access_block, Bucket=name),
            "Encryption": optional(s3.get_bucket_encryption, Bucket=name),
            "Policy": optional(s3.get_bucket_policy, Bucket=name),
            "Tags": optional(s3.get_bucket_tagging, Bucket=name),
            "Objects": {o["Key"]: o["ETag"] for o in pages(s3, "list_objects_v2", "Contents", Bucket=name)},
        }
    return out


def main() -> None:
    instances = [i for r in pages(ec2, "describe_instances", "Reservations") for i in r["Instances"]]
    snap = {
        "ec2/vpcs": keyed(pages(ec2, "describe_vpcs", "Vpcs"), "VpcId"),
        "ec2/subnets": keyed(pages(ec2, "describe_subnets", "Subnets"), "SubnetId"),
        "ec2/route-tables": keyed(pages(ec2, "describe_route_tables", "RouteTables"), "RouteTableId"),
        "ec2/internet-gateways": keyed(
            pages(ec2, "describe_internet_gateways", "InternetGateways"), "InternetGatewayId"
        ),
        "ec2/security-groups": keyed(
            pages(ec2, "describe_security_groups", "SecurityGroups"), "GroupId", "GroupName"
        ),
        "ec2/instances": keyed(instances, "InstanceId"),
        "ec2/volumes": keyed(pages(ec2, "describe_volumes", "Volumes"), "VolumeId"),
        "ec2/addresses": keyed(ec2.describe_addresses()["Addresses"], "AllocationId"),
        "iam/roles": roles(),
        "iam/policies": policies(),
        "iam/instance-profiles": keyed(
            pages(iam, "list_instance_profiles", "InstanceProfiles"), "InstanceProfileName"
        ),
        "iam/users": keyed(pages(iam, "list_users", "Users"), "UserName"),
        "s3/buckets": buckets(),
    }
    json.dump(snap, sys.stdout, default=str, sort_keys=True)


if __name__ == "__main__":
    main()
