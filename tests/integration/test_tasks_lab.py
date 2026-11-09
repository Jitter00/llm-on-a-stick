"""Every built-in task is sound: its oracle passes and doing nothing doesn't.

Run with: uv run pytest -m lab tests/integration/test_tasks_lab.py
NETCONF oracles need `sshpass` on the host (`sudo apt install sshpass`).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from labutil import service_session

from llm_on_a_stick import paths, tasks
from llm_on_a_stick.grading import validate
from llm_on_a_stick.grading.labstate import DockerLabState

pytestmark = pytest.mark.lab

TASKS = sorted(tasks.discover([paths.sections_dir()]), key=lambda p: p.parent.name)


@pytest.fixture(scope="module")
def tools(lab: None) -> Iterator[None]:
    if shutil.which("sshpass") is None:
        pytest.skip("the NETCONF oracles need sshpass on the host (sudo apt install sshpass)")
    # The services the built-in tasks need (cfg-mgmt: Oxidized; netbox: NetBox, reset by each task's start).
    with service_session("oxidized"), service_session("netbox"):
        yield


@pytest.mark.parametrize("task_file", TASKS, ids=[p.parent.name for p in TASKS])
def test_task_is_valid(tools: None, task_file: Path, tmp_path: Path) -> None:
    task = tasks.load_task(task_file)
    result = validate.validate(task, DockerLabState(task.topology), tmp_path / "runs")
    assert result.ok, result.problem
