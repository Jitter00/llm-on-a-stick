"""Cloud checks: the emulated AWS account (the `moto` service) and Terraform working directories.

The emulator stores and returns resources but enforces nothing (no packets, no IAM), so these checks look at
resource state, never at behaviour.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from llm_on_a_stick.grading import awsstate
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext, ServiceUnavailable

SAMPLE = 10


def _run(ctx: GradeContext | None, command: str, cwd: str = "", timeout_s: int = 120) -> tuple[int, str, str]:
    try:
        res = awsstate.run(command, ctx.run.workspace if ctx else None, cwd, timeout_s)
    except awsstate.AwsStateError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    if res.returncode != 0 and awsstate.unreachable(res.stderr + res.stdout):
        raise ServiceUnavailable(f"the AWS emulator is not reachable: {res.stderr.strip()[-300:]}")
    return res.returncode, res.stdout, res.stderr


def _canonical(value: Any) -> Any:
    """Lists compare as sets (AWS returns them in no promised order), numbers and strings by their text."""
    if isinstance(value, list):
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    return value if value is None or isinstance(value, bool) else str(value)


@check("aws_query")
def aws_query(
    ctx: GradeContext,
    command: str,
    query: str | None = None,
    expect: Any = None,
    count: int | None = None,
    min: int | None = None,
) -> Verdict:
    """The answer of `aws <command>` (e.g. "ec2 describe-vpcs --filters Name=cidr,Values=10.0.0.0/16"),
    reduced with the JMESPath `query`: equal to `expect` (lists in any order), or a list of exactly `count`
    or at least `min` items. An AWS error (the resource doesn't exist) fails the check."""
    if sum(p is not None for p in (expect, count, min)) != 1:
        raise ValueError("aws_query needs exactly one of expect, count, min")
    argv = f"aws {command} --output json" + (f" --query {shlex.quote(query)}" if query else "")
    code, out, err = _run(None, argv)
    shown = f"aws {command}" + (f" [{query}]" if query else "")
    if code != 0:
        return Verdict(
            "fail", f"{shown}: {err.strip().splitlines()[-1][:300] if err.strip() else 'failed'}",
            hints=["missing-object"],
        )  # fmt: skip
    got = json.loads(out) if out.strip() else None
    if expect is not None:
        if _canonical(got) == _canonical(expect):
            return Verdict("pass", f"{shown}: as expected", expected=expect)
        empty = got is None or got == [] or got == {}
        return Verdict(
            "fail", f"{shown}: not what was asked", expected=expect, observed=got,
            hints=["missing-object" if empty else "wrong-config"],
        )  # fmt: skip
    found = len(got) if isinstance(got, list) else (0 if got is None else 1)
    expected = {"count": count} if count is not None else {"min": min}
    if (found == count) if count is not None else (found >= (min or 0)):
        return Verdict("pass", f"{shown}: {found} match(es)", expected=expected, observed=found)
    return Verdict(
        "fail", f"{shown}: {found} match(es)", expected=expected, observed=found,
        hints=["missing-object" if found == 0 or min is not None else "wrong-config"],
    )  # fmt: skip


def _many(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else [] if value is None else [str(value)]


def _grants(document: Any) -> set[tuple[str, str, str]]:
    """An IAM policy document as (effect, action, target) triples: one per action and resource, or per
    action and principal for a trust policy. Statements may be split or merged, and a single value may be
    a string or a list: the triples are the same. Conditions are ignored."""
    if isinstance(document, str):
        document = json.loads(document)
    statements = document.get("Statement", []) if isinstance(document, dict) else []
    out = set()
    for st in [statements] if isinstance(statements, dict) else statements:
        principal = st.get("Principal")
        targets = _many(st.get("Resource")) + (
            [p for v in principal.values() for p in _many(v)]
            if isinstance(principal, dict)
            else _many(principal)
        )
        for action in _many(st.get("Action")):
            out |= {(str(st.get("Effect")), action, target) for target in targets}
    return out


def _rows(grants: set[tuple[str, str, str]]) -> list[list[str]]:
    return [list(g) for g in sorted(grants)]


@check("aws_policy_grants")
def aws_policy_grants(
    ctx: GradeContext,
    command: str,
    query: str,
    grants: list[list[str]],
    resolve: dict[str, str] | None = None,
) -> Verdict:
    """The IAM policy document that `aws <command>` returns at the JMESPath `query` grants exactly `grants`,
    a list of [effect, action, resource or principal], e.g. ["Allow", "s3:GetObject", "arn:aws:s3:::b/x/*"]:
    nothing missing and nothing more (a wildcard action or resource is more). Works for a role's trust
    policy too: ["Allow", "sts:AssumeRole", "ec2.amazonaws.com"]. For an ARN only the account knows,
    `resolve` maps a name to an `aws` command that prints it (`CMK: kms describe-key --key-id alias/x
    --query KeyMetadata.Arn`), and the grants write it as `<CMK>`."""
    for name, lookup in (resolve or {}).items():
        code, out, err = _run(None, f"aws {lookup} --output text")
        if code != 0 or not out.strip():
            return Verdict("error", f"aws {lookup}: {err.strip()[-300:] or 'no answer'}", hints=["env-error"])
        grants = [[str(part).replace(f"<{name}>", out.strip()) for part in grant] for grant in grants]
    code, out, err = _run(None, f"aws {command} --output json --query {shlex.quote(query)}")
    if code != 0:
        return Verdict(
            "fail", f"aws {command}: {err.strip().splitlines()[-1][:300] if err.strip() else 'failed'}",
            hints=["missing-object"],
        )  # fmt: skip
    want = {(str(e), str(a), str(t)) for e, a, t in grants}
    try:
        got = _grants(json.loads(out) if out.strip() else None)
    except (ValueError, AttributeError):
        return Verdict("fail", f"aws {command}: not a policy document", hints=["wrong-format"])
    if got == want:
        return Verdict("pass", f"the policy grants exactly the {len(want)} expected permission(s)")
    return Verdict(
        "fail", f"the policy lacks {len(want - got)} expected permission(s), grants {len(got - want)} more",
        expected=_rows(want), observed={"missing": _rows(want - got), "extra": _rows(got - want)},
        hints=["missing-object" if not got else "wrong-config"],
    )  # fmt: skip


@check("aws_unchanged")
def aws_unchanged(
    ctx: GradeContext,
    allow_new: list[str] | None = None,
    allow_changed: list[str] | None = None,
    allow_deleted: list[str] | None = None,
) -> Verdict:
    """The AWS account matches its state at `stick task start` (baseline/moto.json), except what the lists
    allow. An entry is a kind (`ec2/subnets`: any of them) or `kind:label` for one resource, the label being
    its Name tag, else its name (`ec2/security-groups:web`, `iam/roles:app`), else its id. Kinds: ec2/vpcs,
    subnets, route-tables, internet-gateways, security-groups, network-acls, instances, volumes, snapshots,
    images, addresses; iam/roles, policies, instance-profiles, users; s3/buckets; sqs/queues."""
    path = ctx.run.baseline_dir / f"{awsstate.SERVICE}.json"
    if not path.exists():
        return Verdict(
            "error", "no AWS baseline: the task must list moto under requires.services", hints=["env-error"]
        )
    before: awsstate.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    try:
        after = awsstate.snapshot()
    except awsstate.AwsStateError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    allowed = {
        "allow_new": allow_new or [],
        "allow_changed": allow_changed or [],
        "allow_deleted": allow_deleted or [],
    }
    problems = awsstate.diff(before, after, **allowed)
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected=allowed, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "nothing else changed in the AWS account")


@check("aws_reachable")
def aws_reachable(
    ctx: GradeContext, instance: str, port: int, source: str = "198.51.100.10", reachable: bool = True
) -> Verdict:
    """A TCP connection from the internet address `source` to `port` on the running instance with the Name
    tag `instance` would get through (or, with `reachable: false`, would not), judging by the account's
    state: a public address, the subnet's route to an attached internet gateway, the network ACL in both
    directions, a security group rule. Whichever way it was fixed (or left closed) counts."""
    try:
        found = awsstate.blockers(awsstate.snapshot(), instance, int(port), source)
    except awsstate.AwsStateError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    what = f"TCP {port} on {instance} from {source}"
    if reachable:
        if not found:
            return Verdict("pass", f"{what}: gets through")
        return Verdict(
            "fail", f"{what}: stopped in {len(found)} place(s)", observed=found, hints=["wrong-config"]
        )
    if found:
        return Verdict("pass", f"{what}: still closed", observed=found[:SAMPLE])
    return Verdict("fail", f"{what}: gets through, and must not", hints=["collateral-change"])


def _terraform_dir(ctx: GradeContext, path: str) -> Verdict | None:
    directory = ctx.workspace_file(path)
    if not directory.is_dir() or not any(directory.glob("*.tf")):
        return Verdict("fail", f"{path}: no Terraform configuration (*.tf) there", hints=["no-output"])
    return None


def _relative(ctx: GradeContext, path: str) -> str:
    return ctx.workspace_file(path).relative_to(ctx.run.workspace.resolve()).as_posix()


@check("terraform_plan_clean")
def terraform_plan_clean(ctx: GradeContext, path: str = ".") -> Verdict:
    """`terraform plan` in the workspace directory `path` reports no changes: the configuration, the state
    and the real resources agree (it refreshes, so changes made outside Terraform show up too). A plan that
    fails (not initialised, invalid configuration) fails the check."""
    if (missing := _terraform_dir(ctx, path)) is not None:
        return missing
    code, out, err = _run(
        ctx, "terraform plan -detailed-exitcode -input=false -no-color -lock=false", _relative(ctx, path), 300
    )
    if code == 0:
        return Verdict("pass", f"{path}: terraform plan has no changes")
    if code == 2:
        lines = [ln.strip() for ln in out.splitlines() if ln.lstrip().startswith(("# ", "Plan:"))]
        summary = next((ln for ln in lines if ln.startswith("Plan:")), "changes pending")
        return Verdict(
            "fail", f"{path}: terraform plan is not clean ({summary})",
            expected="No changes", observed=lines[:SAMPLE], hints=["wrong-config"],
        )  # fmt: skip
    errors = [ln.strip() for ln in (err or out).splitlines() if ln.strip()]
    return Verdict("fail", f"{path}: terraform plan failed", observed=errors[:SAMPLE], hints=["wrong-format"])


@check("terraform_state_has")
def terraform_state_has(
    ctx: GradeContext,
    path: str = ".",
    addresses: list[str] | None = None,
    types: dict[str, int] | None = None,
    count: int | None = None,
) -> Verdict:
    """The Terraform state in the workspace directory `path` manages every resource in `addresses`
    (e.g. aws_vpc.main, aws_subnet.app["a"]), at least `types` resources of each type ({aws_subnet: 2},
    whatever their names or modules), and exactly `count` resources if given."""
    if (missing := _terraform_dir(ctx, path)) is not None:
        return missing
    code, out, err = _run(ctx, "terraform state list -no-color", _relative(ctx, path))
    if code != 0 and "No state file" not in err + out:
        errors = [ln.strip() for ln in (err or out).splitlines() if ln.strip()]
        return Verdict(
            "fail", f"{path}: terraform state list failed", observed=errors[:SAMPLE], hints=["wrong-format"]
        )
    have = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("data.")]
    lacking = [a for a in addresses or [] if a not in have]
    # module.net.aws_subnet.app["a"] -> aws_subnet: the type is the part before the resource's name.
    kinds = [a.split("[")[0].split(".")[-2] for a in have if "." in a]
    lacking += [f"{n} x {t}" for t, n in (types or {}).items() if kinds.count(t) < n]
    expected = {"addresses": addresses or [], "types": types or {}, "count": count}
    if lacking:
        return Verdict(
            "fail", f"{path}: the state lacks {len(lacking)} expected resource(s)",
            expected=expected, observed={"missing": lacking, "state": have[:SAMPLE]},
            hints=["missing-object"],
        )  # fmt: skip
    if count is not None and len(have) != count:
        return Verdict(
            "fail", f"{path}: the state holds {len(have)} resource(s), expected {count}",
            expected=expected, observed=have[:SAMPLE], hints=["wrong-config"],
        )  # fmt: skip
    return Verdict("pass", f"{path}: the state manages {len(have)} resource(s)", expected=expected)
