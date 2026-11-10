#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . python3 - <<'SCRIPT'
import json

import boto3

ec2 = boto3.client("ec2")
groups = {g["GroupId"]: g for g in ec2.describe_security_groups()["SecurityGroups"]}


def opens_ssh(rule):
    if rule["IpProtocol"] not in ("tcp", "6", "-1"):
        return False
    if rule["IpProtocol"] != "-1" and not rule["FromPort"] <= 22 <= rule["ToPort"]:
        return False
    sources = [r["CidrIp"] for r in rule["IpRanges"]] + [r["CidrIpv6"] for r in rule["Ipv6Ranges"]]
    return any(s in ("0.0.0.0/0", "::/0") for s in sources)


exposed = []
for reservation in ec2.describe_instances()["Reservations"]:
    for inst in reservation["Instances"]:
        rules = [r for g in inst["SecurityGroups"] for r in groups[g["GroupId"]]["IpPermissions"]]
        if inst["State"]["Name"] != "terminated" and any(opens_ssh(r) for r in rules):
            exposed.append(next(t["Value"] for t in inst["Tags"] if t["Key"] == "Name"))
json.dump({"exposed": sorted(exposed)}, open("answer.json", "w"))
SCRIPT
