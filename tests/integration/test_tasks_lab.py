"""Every built-in task is sound: its oracle passes and doing nothing doesn't. Tasks that come with a
script.yaml (those that work through MCP servers) are also solved through their real tools, the MCP
servers.

Run with: uv run pytest -m lab tests/integration/test_tasks_lab.py
NETCONF oracles need `sshpass` on the host (`sudo apt install sshpass`).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from labutil import service_session

from llm_on_a_stick import paths, tasks
from llm_on_a_stick.grading import validate
from llm_on_a_stick.grading.labstate import NO_LAB, DockerLabState
from llm_on_a_stick.runner import loop, mcp, models

pytestmark = pytest.mark.lab

TASKS = sorted(tasks.discover([paths.sections_dir()]), key=lambda p: p.parent.name)
SCRIPTED = [p for p in TASKS if (p.parent / "script.yaml").exists()]


@pytest.fixture(scope="module")
def tools(request: pytest.FixtureRequest) -> Iterator[None]:
    # The services the selected tasks need (cfg-mgmt: Oxidized; netbox, nautobot, moto: reset by each task's
    # start), and only those: CI may have selected one section (see conftest.py).
    selected = {
        item.callspec.id  # type: ignore[attr-defined]
        for item in request.session.items
        if item.path.name == Path(__file__).name
    }
    chosen = [tasks.load_task(path) for path in TASKS if path.parent.name in selected]
    # The lab too, unless every selected task is `topology: none` (the cloud sections: only moto is needed).
    if any(task.topology != NO_LAB for task in chosen):
        if shutil.which("sshpass") is None:
            pytest.skip("the NETCONF oracles need sshpass on the host (sudo apt install sshpass)")
        request.getfixturevalue("lab")
    needed: set[str] = set()
    for task in chosen:
        needed.update(task.requires.get("services") or [])
    with ExitStack() as stack:
        for name in sorted(needed):
            stack.enter_context(service_session(name))
        yield


@pytest.mark.parametrize("task_file", TASKS, ids=[p.parent.name for p in TASKS])
def test_task_is_valid(tools: None, task_file: Path, tmp_path: Path) -> None:
    task = tasks.load_task(task_file)
    result = validate.validate(task, DockerLabState(task.topology), tmp_path / "runs")
    assert result.ok, result.problem


@pytest.mark.parametrize("task_file", SCRIPTED, ids=[p.parent.name for p in SCRIPTED])
def test_task_script_passes_through_the_real_tools(tools: None, task_file: Path, tmp_path: Path) -> None:
    """The oracle proves the task can be solved; its script proves it can be solved with what the model
    gets: the pinned MCP servers, started as in a run, with the tools the task's services allow."""
    task = tasks.load_task(task_file)
    mcp.ensure_image()
    client = models.make_client(f"script/{task_file.parent / 'script.yaml'}")
    client.check()
    info, result, m = loop.run_task(task, client, DockerLabState(task.topology), tmp_path / "runs")
    failed = [f"{c.name}: {c.message}" for c in result.checks if c.status != "pass"]
    assert result.outcome == "pass", f"{m.stop_reason} {m.error} {failed} (see {info.run_dir})"
    assert m.tools_mode == "mcp" and m.tool_errors == 0 and m.command_failures == 0
