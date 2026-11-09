"""moto (the emulated AWS account) with the toolbox's tools: aws, boto3 and Terraform reach it, reset empties
it. Needs Docker and the toolbox image, not the lab.

Run with: uv run pytest -m lab tests/integration/test_moto.py
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from labutil import service_session

from llm_on_a_stick import lab as lab_consts
from llm_on_a_stick.grading import awsstate
from llm_on_a_stick.runner import toolbox
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.spec import ServiceSpec

pytestmark = pytest.mark.lab

MAIN_TF = """
terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

provider "aws" {}

resource "aws_vpc" "main" {
  cidr_block = "10.90.0.0/16"
  tags       = { Name = "from-terraform" }
}
"""


@pytest.fixture(scope="module")
def moto() -> Iterator[ServiceSpec]:
    toolbox.ensure_image()
    with service_session("moto") as spec:
        lifecycle.restore_snapshot(spec)  # start from an empty account, whatever ran before
        yield spec


def vpc_names() -> list[str]:
    return sorted(v["label"] for v in awsstate.snapshot()["ec2/vpcs"].values())


def test_aws_cli_changes_show_in_the_snapshot_and_reset_removes_them(moto: ServiceSpec) -> None:
    before = awsstate.snapshot()
    tags = "ResourceType=vpc,Tags=[{Key=Name,Value=from-cli}]"
    res = awsstate.run(f"aws ec2 create-vpc --cidr-block 10.91.0.0/16 --tag-specifications '{tags}'")
    assert res.returncode == 0, res.stderr
    after = awsstate.snapshot()
    assert "from-cli" in vpc_names()
    assert "ec2/vpcs: added from-cli" in awsstate.diff(before, after, [], [], [])
    assert awsstate.diff(after, awsstate.snapshot(), [], [], []) == []  # reading twice: no difference

    lifecycle.restore_snapshot(moto)
    assert "from-cli" not in vpc_names()


def test_terraform_installs_its_provider_offline_and_applies(moto: ServiceSpec, tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(MAIN_TF, encoding="utf-8")
    # No registry: the provider must come from the copy in the image.
    command = "terraform init -input=false -plugin-dir=/usr/share/terraform/plugins && " + (
        "terraform apply -auto-approve -input=false -no-color"
    )
    res = awsstate.run(command, workspace=tmp_path, timeout_s=300)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "from-terraform" in vpc_names()
    plan = awsstate.run("terraform plan -detailed-exitcode -input=false", workspace=tmp_path, timeout_s=300)
    assert plan.returncode == 0, plan.stdout  # nothing left to change
    lifecycle.restore_snapshot(moto)


def test_boto3_reads_the_endpoint_from_the_environment(moto: ServiceSpec) -> None:
    res = awsstate.run(
        'python3 -c \'import boto3; print(boto3.client("sts").get_caller_identity()["Account"])\''
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "123456789012"


def test_reachable_from_the_lab_network(moto: ServiceSpec) -> None:
    """Lab nodes and other services reach moto at its fixed management address."""
    url = f"http://{lab_consts.SERVICE_IPS['moto']}:5000/moto-api/"
    res = subprocess.run(
        ["docker", "run", "--rm", "--network", lab_consts.MGMT_NETWORK, toolbox.IMAGE,
         "curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", url],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.stdout.strip() == "200", res.stderr
