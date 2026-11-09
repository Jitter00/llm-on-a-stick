"""Unit tests for the cloud sections: the moto service, lab-free tasks, the AWS and Terraform checks.

No Docker: the toolbox commands the checks run are replaced by canned results.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import paths, services
from llm_on_a_stick.grading import awsstate, canaries, run
from llm_on_a_stick.grading.checks import aws as aws_checks
from llm_on_a_stick.grading.labstate import NO_LAB, DockerLabState
from llm_on_a_stick.runner import toolbox
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.spec import HttpSnapshot
from llm_on_a_stick.tasks import load_task
from test_grading import check, make_ctx

AWS_TASK = paths.sections_dir() / "aws" / "aws-query-instance"


def done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Canned toolbox: `tool["reply"]` is what the next commands return; the commands are recorded."""
    box: dict[str, Any] = {"reply": done(), "commands": []}

    def fake(command: str, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        box["commands"].append(command)
        return box["reply"](command) if callable(box["reply"]) else box["reply"]

    monkeypatch.setattr(awsstate, "run", fake)
    return box


# --------------------------------------------------------------------------- the service


def test_moto_service_resets_over_http_and_gives_tools_their_environment() -> None:
    spec = services.load("moto", env={})
    assert isinstance(spec.snapshot, HttpSnapshot)
    assert spec.snapshot.url == "http://127.0.0.1:8083/moto-api/reset"
    assert spec.seed is None and lifecycle.has_snapshot(spec)  # the baseline is the empty account
    assert spec.env["AWS_ENDPOINT_URL"] == "http://127.0.0.1:8083"
    assert {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"} <= set(spec.env)
    assert services.load("moto", env={"STICK_MOTO_PORT": "9000"}).env["AWS_ENDPOINT_URL"].endswith(":9000")


def test_http_reset_sends_one_request_and_starts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def urlopen(req: Any, timeout: float) -> Reply:
        sent.append((req.get_method(), req.full_url))
        return Reply()

    monkeypatch.setattr(lifecycle.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(lifecycle, "_run", lambda *a, **k: pytest.fail("no docker command expected"))
    lifecycle.restore_snapshot(services.load("moto", env={}))
    assert sent == [("POST", "http://127.0.0.1:8083/moto-api/reset")]


def test_service_env_is_only_for_tasks_that_require_the_service() -> None:
    assert run.service_env([]) == {}
    assert run.service_env(["netbox", "unknown"]) == {}
    assert run.service_env(["moto"])["AWS_DEFAULT_REGION"] == "eu-west-1"
    assert "auth" not in run.service_vars()["moto"]  # no token: the tools read the environment


def test_toolbox_passes_the_environment_to_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(toolbox.subprocess, "run", lambda argv, **kw: calls.append(argv) or done())
    toolbox.Toolbox(tmp_path, "box", env={"AWS_ENDPOINT_URL": "http://x"}).start()
    toolbox.run_once("aws sts get-caller-identity", {"A": "1"}, workspace=tmp_path, cwd="net")
    assert calls[0][calls[0].index("-e") + 1] == "AWS_ENDPOINT_URL=http://x"
    assert "A=1" in calls[1] and "/work/net" in calls[1] and calls[1][-1] == "aws sts get-caller-identity"


def test_an_older_toolbox_image_is_rebuilt(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(toolbox.containerlab, "build_image", built.append)
    for label, expected in ((toolbox.TOOLBOX_VERSION, []), ("<no value>", ["toolbox"]), (None, ["toolbox"])):
        built.clear()
        reply = done(1) if label is None else done(out=f"{label}\n")  # None: no such image
        monkeypatch.setattr(toolbox.subprocess, "run", lambda argv, reply=reply, **kw: reply)
        toolbox.ensure_image(log=None)
        assert built == expected, label


# --------------------------------------------------------------------------- lab-free tasks


def test_topology_none_has_no_nodes_and_needs_no_lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = DockerLabState(NO_LAB)
    assert lab.nodes() == {}
    task = load_task(AWS_TASK)
    assert task.topology == NO_LAB
    events: list[str] = []
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: events.append(f"reset {spec.name}"))
    monkeypatch.setattr(run, "run_script", lambda task, script, kind, *_: events.append(kind))
    monkeypatch.setattr(run.awsstate, "snapshot", lambda: {"ec2/vpcs": {"vpc-1": {"label": "x"}}})
    info = run.start(task, tmp_path / "runs", lab)
    assert events == ["reset moto", "setup"]
    assert json.loads((info.baseline_dir / "moto.json").read_text()) == {
        "ec2/vpcs": {"vpc-1": {"label": "x"}}
    }
    assert list(info.baseline_dir.glob("*.cfg")) == []  # no router to baseline
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, lab)
    assert env["AWS_ENDPOINT_URL"].startswith("http://127.0.0.1:")


def test_start_explains_a_moto_that_is_not_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def down() -> None:
        raise awsstate.AwsStateError("connection refused")

    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: None)
    monkeypatch.setattr(run, "run_script", lambda *a: None)
    monkeypatch.setattr(run.awsstate, "snapshot", down)
    with pytest.raises(run.RunError, match="stick svc up moto"):
        run.start(load_task(AWS_TASK), tmp_path / "runs", DockerLabState(NO_LAB))


def test_net16_canary_is_a_private_16() -> None:
    values = canaries.generate({"a": "net16", "b": "net16"}, seed=1)
    assert values["a"] != values["b"]
    for value in values.values():
        first, second = value.split(".")
        assert first == "10" and 64 <= int(second) <= 127


# --------------------------------------------------------------------------- state diff


def account() -> awsstate.Snapshot:
    return {
        "ec2/security-groups": {
            "sg-1": {"label": "web", "IpPermissions": [{"FromPort": 22}]},
            "sg-2": {"label": "db", "IpPermissions": []},
        },
        "ec2/volumes": {"vol-1": {"label": "scratch", "State": "available"}},
    }


def test_diff_reports_added_changed_and_deleted_by_label() -> None:
    after = account()
    after["ec2/security-groups"]["sg-1"]["IpPermissions"] = []
    after["ec2/security-groups"]["sg-3"] = {"label": "new"}
    del after["ec2/volumes"]["vol-1"]
    assert awsstate.diff(account(), after, [], [], []) == [
        "ec2/security-groups: changed web (IpPermissions)",
        "ec2/security-groups: added new",
        "ec2/volumes: deleted scratch",
    ]


def test_diff_allows_a_kind_or_one_labelled_resource() -> None:
    after = account()
    after["ec2/security-groups"]["sg-1"]["IpPermissions"] = []
    after["ec2/security-groups"]["sg-2"]["IpPermissions"] = [{"FromPort": 1}]
    del after["ec2/volumes"]["vol-1"]
    problems = awsstate.diff(account(), after, [], ["ec2/security-groups:web"], ["ec2/volumes"])
    assert problems == ["ec2/security-groups: changed db (IpPermissions)"]
    # A recreated group has a new id: the old one counts as deleted, whatever its name.
    recreated = account()
    recreated["ec2/security-groups"]["sg-9"] = recreated["ec2/security-groups"].pop("sg-1")
    assert "ec2/security-groups: deleted web" in awsstate.diff(
        account(), recreated, ["ec2/security-groups:web"], ["ec2/security-groups:web"], []
    )


def test_aws_unchanged_compares_with_the_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = make_ctx(tmp_path)
    assert check(ctx, "aws_unchanged").hints == ["env-error"]  # no baseline: moto not in requires.services
    (ctx.run.baseline_dir / "moto.json").write_text(json.dumps(account()))
    after = account()
    monkeypatch.setattr(awsstate, "snapshot", lambda: after)
    assert check(ctx, "aws_unchanged").status == "pass"
    del after["ec2/volumes"]["vol-1"]
    res = check(ctx, "aws_unchanged")
    assert res.status == "fail" and res.hints == ["collateral-change"]
    assert res.observed == ["ec2/volumes: deleted scratch"]
    assert check(ctx, "aws_unchanged", allow_deleted=["ec2/volumes:scratch"]).status == "pass"


# --------------------------------------------------------------------------- aws_query, aws_policy_grants


def test_aws_query_expect_ignores_list_order(tmp_path: Path, tool: dict[str, Any]) -> None:
    ctx = make_ctx(tmp_path, canary={"name": "stick-abc"})
    tool["reply"] = done(out='[{"cidr": "10.1.2.0/24", "az": "b"}, {"cidr": "10.1.1.0/24", "az": "a"}]')
    expect = [{"cidr": "10.1.1.0/24", "az": "a"}, {"cidr": "10.1.2.0/24", "az": "b"}]
    command = "ec2 describe-subnets --filters Name=tag:Name,Values={{ canaries.name }}"
    assert check(ctx, "aws_query", command=command, query="Subnets[]", expect=expect).status == "pass"
    assert tool["commands"] == [
        "aws ec2 describe-subnets --filters Name=tag:Name,Values=stick-abc --output json --query 'Subnets[]'"
    ]
    res = check(ctx, "aws_query", command=command, expect=expect[:1])
    assert res.status == "fail" and res.hints == ["wrong-config"]


def test_aws_query_counts_and_treats_an_aws_error_as_missing(tmp_path: Path, tool: dict[str, Any]) -> None:
    ctx = make_ctx(tmp_path)
    tool["reply"] = done(out="[]")
    assert check(ctx, "aws_query", command="ec2 describe-volumes", count=0).status == "pass"
    assert check(ctx, "aws_query", command="ec2 describe-volumes", min=1).hints == ["missing-object"]
    assert check(ctx, "aws_query", command="ec2 describe-vpcs", expect=["x"]).hints == ["missing-object"]
    tool["reply"] = done(254, err="An error occurred (NoSuchEntity) when calling the GetRole operation")
    res = check(ctx, "aws_query", command="iam get-role --role-name x", expect={})
    assert res.status == "fail" and "NoSuchEntity" in res.message
    # Two expectations at once is a task-authoring mistake.
    assert check(ctx, "aws_query", command="x", count=1, min=1).status == "error"


def test_an_unreachable_emulator_is_an_env_error_not_a_failure(tmp_path: Path, tool: dict[str, Any]) -> None:
    tool["reply"] = done(255, err='Could not connect to the endpoint URL: "http://127.0.0.1:8083/"')
    res = check(make_ctx(tmp_path), "aws_query", command="ec2 describe-vpcs", count=0)
    assert res.status == "error" and res.hints == ["env-error"]


def test_policy_grants_are_the_same_however_statements_are_written() -> None:
    merged = {
        "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": "arn:b"}]
    }
    split = {
        "Statement": [
            {"Effect": "Allow", "Action": "s3:GetObject", "Resource": ["arn:b"]},
            {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:b"},
        ]
    }
    assert aws_checks._grants(merged) == aws_checks._grants(json.dumps(split))
    trust = {
        "Statement": {
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    }
    assert aws_checks._grants(trust) == {("Allow", "sts:AssumeRole", "ec2.amazonaws.com")}


def test_aws_policy_grants_wants_exactly_the_listed_permissions(tmp_path: Path, tool: dict[str, Any]) -> None:
    ctx = make_ctx(tmp_path)
    grants = [["Allow", "s3:GetObject", "arn:aws:s3:::b/reports/*"]]
    policy = {
        "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/reports/*"}]
    }
    params = {"command": "iam get-role-policy --role-name r --policy-name p", "query": "PolicyDocument"}
    tool["reply"] = done(out=json.dumps(policy))
    assert check(ctx, "aws_policy_grants", grants=grants, **params).status == "pass"
    policy["Statement"][0]["Action"] = "s3:*"  # more than asked
    tool["reply"] = done(out=json.dumps(policy))
    res = check(ctx, "aws_policy_grants", grants=grants, **params)
    assert res.status == "fail" and res.hints == ["wrong-config"]
    assert res.observed["extra"] == [["Allow", "s3:*", "arn:aws:s3:::b/reports/*"]]
    tool["reply"] = done(254, err="An error occurred (NoSuchEntity)")
    assert check(ctx, "aws_policy_grants", grants=grants, **params).hints == ["missing-object"]


# --------------------------------------------------------------------------- terraform


def test_terraform_plan_clean_reads_the_exit_code(tmp_path: Path, tool: dict[str, Any]) -> None:
    ctx = make_ctx(tmp_path)
    assert check(ctx, "terraform_plan_clean", path="net").hints == ["no-output"]  # no configuration
    (ctx.run.workspace / "net").mkdir()
    (ctx.run.workspace / "net" / "main.tf").write_text("")
    assert check(ctx, "terraform_plan_clean", path="net").status == "pass"
    assert "-detailed-exitcode" in tool["commands"][-1]
    tool["reply"] = done(2, out="  # aws_vpc.main will be updated in-place\nPlan: 0 to add, 1 to change.\n")
    res = check(ctx, "terraform_plan_clean", path="net")
    assert res.status == "fail" and res.hints == ["wrong-config"] and "1 to change" in res.message
    tool["reply"] = done(1, err="Error: Inconsistent dependency lock file")
    assert check(ctx, "terraform_plan_clean", path="net").hints == ["wrong-format"]
    assert check(ctx, "terraform_plan_clean", path="../x").status == "error"  # outside the workspace


def test_terraform_state_has_addresses_types_and_count(tmp_path: Path, tool: dict[str, Any]) -> None:
    ctx = make_ctx(tmp_path)
    (ctx.run.workspace / "main.tf").write_text("")
    state = 'data.aws_ami.linux\naws_vpc.main\naws_subnet.app["a"]\nmodule.net.aws_subnet.b\n'
    tool["reply"] = done(out=state)
    assert (
        check(ctx, "terraform_state_has", addresses=["aws_vpc.main", 'aws_subnet.app["a"]']).status == "pass"
    )
    assert check(ctx, "terraform_state_has", types={"aws_subnet": 2, "aws_vpc": 1}, count=3).status == "pass"
    res = check(ctx, "terraform_state_has", types={"aws_subnet": 3}, addresses=["aws_vpc.other"])
    assert res.status == "fail" and res.observed["missing"] == ["aws_vpc.other", "3 x aws_subnet"]
    assert check(ctx, "terraform_state_has", count=2).hints == ["wrong-config"]
    tool["reply"] = done(1, err="No state file was found!")
    assert check(ctx, "terraform_state_has", addresses=["aws_vpc.main"]).hints == ["missing-object"]
