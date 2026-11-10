"""The emulated AWS account (the `moto` service) for grading: its tools, a snapshot of its resources, and
what changed since.

The grader has no AWS client of its own: it runs the toolbox image's `aws`, `terraform` and a boto3 script
(images/toolbox/aws_snapshot.py), with the environment from services/moto/service.yaml. So it reads the
account through the same tools as the model, in a separate container.

`stick task start` saves the snapshot to baseline/moto.json right after setup; the `aws_unchanged` check
compares it with the account at grading time.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path
from typing import Any

from llm_on_a_stick import services
from llm_on_a_stick.env.containerlab import ContainerlabError
from llm_on_a_stick.runner import toolbox

SERVICE = "moto"
SNAPSHOT_SCRIPT = "/usr/local/lib/stick/aws_snapshot.py"  # in the toolbox image

Snapshot = dict[str, dict[str, dict[str, Any]]]  # kind (ec2/vpcs...) -> resource id -> resource


_image_checked = False


class AwsStateError(RuntimeError):
    pass


def tool_env() -> dict[str, str]:
    """AWS_ENDPOINT_URL, credentials and region for the emulator."""
    return dict(services.load(SERVICE).env)


def run(
    command: str, workspace: Path | None = None, cwd: str = "", timeout_s: int = 120
) -> subprocess.CompletedProcess[str]:
    """Run a command (aws ..., terraform ...) in a throwaway toolbox container against the emulator."""
    global _image_checked
    try:
        if not _image_checked:  # `stick task start` and `stick grade` may be the first to need the image
            toolbox.ensure_image(log=None)
            _image_checked = True
        return toolbox.run_once(command, tool_env(), workspace, cwd, timeout_s)
    except (toolbox.ToolboxError, ContainerlabError) as exc:
        raise AwsStateError(str(exc)) from exc


def unreachable(output: str) -> bool:
    """The tool could not reach the emulator at all (as opposed to AWS answering with an error)."""
    return any(
        text in output
        for text in ("Could not connect to the endpoint URL", "connection refused", "Unable to find image")
    )


def snapshot() -> Snapshot:
    res = run(f"python3 {SNAPSHOT_SCRIPT}")
    if res.returncode != 0:
        tail = " | ".join((res.stderr or res.stdout).strip().splitlines()[-2:])
        raise AwsStateError(f"cannot read the AWS account (exit {res.returncode}): {tail[:400]}")
    data: Snapshot = json.loads(res.stdout)
    return data


def _allowed(kind: str, obj: dict[str, Any], allow: list[str]) -> bool:
    """`allow` entries are a kind ("ec2/volumes": any of them) or kind:label ("ec2/security-groups:web")."""
    return kind in allow or f"{kind}:{obj.get('label')}" in allow


def diff(
    before: Snapshot,
    after: Snapshot,
    allow_new: list[str],
    allow_changed: list[str],
    allow_deleted: list[str],
) -> list[str]:
    """Changes from `before` to `after` that none of the allow lists covers."""
    problems: list[str] = []
    for kind, old in before.items():
        new = after.get(kind, {})
        for rid, obj in old.items():
            if rid not in new:
                if not _allowed(kind, obj, allow_deleted):
                    problems.append(f"{kind}: deleted {obj.get('label', rid)}")
            elif new[rid] != obj and not _allowed(kind, obj, allow_changed):
                fields = sorted(k for k in set(obj) | set(new[rid]) if obj.get(k) != new[rid].get(k))
                problems.append(f"{kind}: changed {obj.get('label', rid)} ({', '.join(fields)})")
        problems += [
            f"{kind}: added {obj.get('label', rid)}"
            for rid, obj in new.items()
            if rid not in old and not _allowed(kind, obj, allow_new)
        ]
    return problems


def _covers(cidr: str | None, address: str) -> bool:
    try:
        return cidr is not None and ipaddress.ip_address(address) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _nacl_allows(acl: dict[str, Any], egress: bool, port: int, address: str) -> bool:
    """A network ACL's verdict on one TCP port to or from `address`: the lowest-numbered matching entry."""
    for entry in sorted(acl.get("Entries", []), key=lambda e: int(e["RuleNumber"])):
        ports = entry.get("PortRange")
        if (
            bool(entry.get("Egress")) == egress
            and str(entry.get("Protocol")) in ("-1", "6")
            and (ports is None or int(ports["From"]) <= port <= int(ports["To"]))
            and _covers(entry.get("CidrBlock"), address)
        ):
            return str(entry.get("RuleAction")) == "allow"
    return False


EPHEMERAL = (1024, 32768, 49152, 65535)  # the replies leave from the client's port: any of 1024-65535


def blockers(snap: Snapshot, instance: str, port: int, source: str) -> list[str]:
    """What stops a TCP connection from the internet address `source` to `port` on the instance labelled
    `instance`, read off the account's state (the emulator carries no packets): the instance's public
    address, its subnet's route to an attached internet gateway, the subnet's network ACL in both
    directions, and the instance's security groups. Empty: nothing stops it."""
    found = [
        i for i in snap.get("ec2/instances", {}).values()
        if i.get("label") == instance and (i.get("State") or {}).get("Name") == "running"
    ]  # fmt: skip
    if len(found) != 1:
        return [f"{len(found)} running instance(s) named {instance}"]
    inst = found[0]
    subnet, vpc = inst.get("SubnetId"), inst.get("VpcId")
    out = []
    if not inst.get("PublicIpAddress"):
        out.append("the instance has no public IPv4 address")

    tables = [t for t in snap.get("ec2/route-tables", {}).values() if t.get("VpcId") == vpc]
    own = [t for t in tables if any(a.get("SubnetId") == subnet for a in t.get("Associations", []))]
    main = [t for t in tables if any(a.get("Main") for a in t.get("Associations", []))]
    routes = [
        r for t in (own or main)[:1] for r in t.get("Routes", [])
        if r.get("State") != "blackhole" and _covers(r.get("DestinationCidrBlock"), source)
    ]  # fmt: skip
    best = max(routes, key=lambda r: ipaddress.ip_network(r["DestinationCidrBlock"]).prefixlen, default=None)
    gateway = str((best or {}).get("GatewayId") or "")
    attached = any(
        a.get("VpcId") == vpc
        for g in snap.get("ec2/internet-gateways", {}).values()
        if g.get("InternetGatewayId") == gateway
        for a in g.get("Attachments", [])
    )
    if not gateway.startswith("igw-"):
        out.append("the subnet's route table has no route to an internet gateway")
    elif not attached:
        out.append("the internet gateway in the subnet's route is not attached to the VPC")

    every = [a for a in snap.get("ec2/network-acls", {}).values() if a.get("VpcId") == vpc]
    # The snapshot lists a default ACL without its subnets: a subnet with no ACL of its own is on it.
    acls = [a for a in every if any(x.get("SubnetId") == subnet for x in a.get("Associations", []))] or [
        a for a in every if a.get("IsDefault")
    ]
    if not acls or not _nacl_allows(acls[0], False, port, source):
        out.append(f"the subnet's network ACL does not let TCP {port} in")
    if not acls or not all(_nacl_allows(acls[0], True, p, source) for p in EPHEMERAL):
        out.append("the subnet's network ACL does not let the replies out (TCP 1024-65535)")

    groups = {g.get("GroupId") for g in inst.get("SecurityGroups", [])}
    opened = any(
        str(perm.get("IpProtocol")) in ("-1", "tcp", "6")
        and (str(perm.get("IpProtocol")) == "-1" or int(perm["FromPort"]) <= port <= int(perm["ToPort"]))
        and any(_covers(r.get("CidrIp"), source) for r in perm.get("IpRanges", []))
        for gid, group in snap.get("ec2/security-groups", {}).items()
        if gid in groups
        for perm in group.get("IpPermissions", [])
    )
    if not opened:
        out.append(f"none of the instance's security groups allows TCP {port} from {source}")
    return out
