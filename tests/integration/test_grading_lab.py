"""The grader against the live lab: task start (real setup script) -> "agent" -> grade.

Run with: uv run pytest -m lab tests/integration/test_grading_lab.py
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from labutil import dexec, service_session, wait_for

from llm_on_a_stick.grading import grade as grade_mod
from llm_on_a_stick.grading import run
from llm_on_a_stick.grading.checks import run_check
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.grading.labstate import DockerLabState
from llm_on_a_stick.tasks import CheckSpec, load_task

pytestmark = pytest.mark.lab

DEMO = Path(__file__).parents[1] / "fixtures" / "tasks" / "cfg-mgmt" / "demo-frr-config-retrieval"


@pytest.fixture
def started(lab: None, tmp_path: Path) -> run.RunInfo:
    return run.start(load_task(DEMO), tmp_path / "runs", DockerLabState())


def agent_saves_config(info: run.RunInfo) -> str:
    """What an agent gets over SSH as admin (verified byte-identical to this path)."""
    cfg = dexec("frr1", "su", "-s", "/bin/sh", "admin", "-c", 'vtysh -c "show running-config"').stdout
    (info.workspace / "frr1.cfg").write_text(cfg)
    return cfg


def test_setup_planted_the_canary(started: run.RunInfo) -> None:
    canary = started.canaries["host_desc"]
    assert f"description {canary}" in (started.baseline_dir / "frr1.cfg").read_text()
    assert canary in (started.run_dir / "setup.log").read_text()


def test_correct_attempt_passes(started: run.RunInfo) -> None:
    agent_saves_config(started)
    result = grade_mod.grade(started.run_dir)
    assert (result.outcome, result.score) == ("pass", 1.0), result.model_dump_json(indent=2)


def test_truncated_attempt_is_partial(started: run.RunInfo) -> None:
    cfg = agent_saves_config(started)
    (started.workspace / "frr1.cfg").write_text("\n".join(cfg.splitlines()[:12]))
    result = grade_mod.grade(started.run_dir)
    assert result.outcome == "partial"
    assert "truncated-output" in result.failure_hints


def test_collateral_change_is_caught(started: run.RunInfo) -> None:
    agent_saves_config(started)
    original = 'set / interface ethernet-1/1 description "to frr1"'
    try:
        dexec("srl2", "sr_cli", "-ec", "set / interface ethernet-1/1 description changed-by-agent")
        result = grade_mod.grade(started.run_dir)
        assert "collateral-change" in result.failure_hints
        bad = next(c for c in result.checks if c.type == "no_change_outside")
        assert list(bad.observed) == ["srl2"]
    finally:
        dexec("srl2", "sr_cli", "-ec", original)
    assert grade_mod.grade(started.run_dir).outcome == "pass"


@pytest.fixture(scope="module")
def tools(lab: None) -> Iterator[None]:
    with service_session("netbox"), service_session("oxidized"):
        yield


def test_service_checks(tools: None, started: run.RunInfo) -> None:
    ctx = GradeContext(run=started, lab=DockerLabState())
    variables = run.template_vars(started.canaries, started.workspace, ctx.lab)

    def check(type_: str, **params: object) -> str:
        return run_check(CheckSpec(type=type_, params=params), ctx, variables).status

    assert wait_for(lambda: check("oxidized_has_backup", node="frr1") == "pass", timeout=60, interval=3)
    assert (
        check(
            "oxidized_has_backup",
            node="srl1",
            contains=["set / network-instance default protocols bgp autonomous-system 65001"],
        )
        == "pass"
    )
    assert check("oxidized_has_backup", node="frr1", min_versions=99) == "fail"
    assert check("netbox_object", endpoint="dcim/sites", filters={"slug": "stick-lab"}, count=1) == "pass"
    assert check("netbox_object", endpoint="dcim/devices", filters={"name": "srl1"}) == "fail"  # not seeded
