"""The runner against the live lab: a scripted "model" solves a real task through the toolbox container.

Run with: uv run pytest -m lab tests/integration/test_runner_lab.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llm_on_a_stick import paths, tasks
from llm_on_a_stick.grading.labstate import DockerLabState
from llm_on_a_stick.runner import loop, models, toolbox

pytestmark = pytest.mark.lab

SCRIPTS = Path(__file__).parents[1] / "fixtures" / "scripts"


def _leftover_toolboxes() -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=stick-toolbox=1", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout.split()


def test_scripted_model_solves_task_through_toolbox(lab: None, tmp_path: Path) -> None:
    toolbox.ensure_image()
    task = tasks.find_task("running-config-cli-frr", [paths.sections_dir()])
    client = models.make_client(f"script/{SCRIPTS / 'running-config-cli-frr.yaml'}")
    client.check()

    info, result, m = loop.run_task(task, client, DockerLabState(task.topology), tmp_path / "runs")

    assert result.outcome == "pass", [c.message for c in result.checks if c.status != "pass"]
    assert (m.stop_reason, m.tool_calls, m.command_failures) == ("done", 2, 0)
    commands = [
        json.loads(line)
        for line in (info.run_dir / "transcript.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "command"
    ]
    assert commands[1]["output"].startswith(str(len((info.workspace / "frr2.cfg").read_text().splitlines())))
    assert _leftover_toolboxes() == []


def test_command_timeout_and_non_interactive(lab: None, tmp_path: Path) -> None:
    toolbox.ensure_image()
    with toolbox.Toolbox(tmp_path, "stick-toolbox-test", max_output=200) as box:
        slow = box.exec("sleep 30", timeout_s=2)
        assert slow.timed_out and slow.seconds < 15
        # no terminal: a password prompt fails fast instead of hanging
        prompt = box.exec("ssh admin@172.30.30.22 true", timeout_s=20)
        assert prompt.exit_code != 0 and not prompt.timed_out
        big = box.exec("seq 1 10000", timeout_s=10)
        assert big.truncated and "characters omitted" in big.output
    assert _leftover_toolboxes() == []
