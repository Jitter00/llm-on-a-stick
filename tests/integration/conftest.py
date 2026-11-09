"""Session-wide lab fixture (deploy the base lab once), and CI's choice of which lab tests to run.

CI sets STICK_LAB_SECTIONS / _SERVICES / _CORE from the pull request's changed files
(`python -m llm_on_a_stick.labselect`); without them, every lab test runs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from labutil import frr_established_peers, wait_for

from llm_on_a_stick import paths, services, tasks
from llm_on_a_stick.env import containerlab
from llm_on_a_stick.labselect import Selection

HERE = Path(__file__).parent


def _wanted(item: pytest.Item, sel: Selection, task_info: dict[str, tasks.Task]) -> bool:
    if item.path.name == "test_tasks_lab.py":  # one test per task, with the task folder as its id
        task = task_info[item.callspec.id]  # type: ignore[attr-defined]
        return task.section in sel.sections or (sel.core and task.floor)
    service = item.path.stem.removeprefix("test_")
    if service in services.available():  # a service's own tests (test_netbox.py...)
        return service in sel.services
    return sel.core  # the generic lab tests (base lab, grading, runner...)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    sel = Selection.from_env(os.environ)
    if sel is None:
        return
    task_info = {p.parent.name: tasks.load_task(p) for p in tasks.discover([paths.sections_dir()])}
    keep, drop = [], []
    for item in items:
        lab_item = HERE in item.path.parents and item.get_closest_marker("lab") is not None
        (drop if lab_item and not _wanted(item, sel, task_info) else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def _base_lab_running() -> bool:
    try:
        return any(n.state == "running" for n in containerlab.inspect("base"))
    except Exception:  # not deployed (or containerlab can't tell): treat as not running
        return False


@pytest.fixture(scope="session")
def lab() -> Iterator[None]:
    """The base lab, deployed fresh and converged (both leaves have both spine sessions).

    A lab that was already running before the tests (you were using it) is left running afterwards;
    one the tests deployed themselves is destroyed again."""
    was_running = _base_lab_running()
    containerlab.deploy("base", reconfigure=True)
    try:
        converged = wait_for(lambda: all(frr_established_peers(n) == 2 for n in ("frr1", "frr2")))
        assert converged, "base lab BGP did not converge"
        yield
    finally:
        if not was_running:
            containerlab.destroy("base")
