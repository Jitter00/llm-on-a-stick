"""`stick task start`: prepare one attempt at a task.

A run directory holds everything about one attempt:
    run.json       task id, task dir, canaries, rendered prompt, timestamps
    work/          the agent's workspace (files the task asks for go here)
    baseline/      every router's config right after setup (for collateral-change checks)
    setup.log      output of the task's setup script, if any
    result.json    written later by `stick grade`
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from llm_on_a_stick.grading import canaries as canary_mod
from llm_on_a_stick.grading.labstate import LabState
from llm_on_a_stick.grading.template import render
from llm_on_a_stick.tasks import Task


class RunError(RuntimeError):
    pass


class RunInfo(BaseModel):
    task_id: str
    task_dir: Path
    run_id: str
    run_dir: Path
    started_at: datetime
    canaries: dict[str, str]
    prompt: str
    topology: str

    @property
    def workspace(self) -> Path:
        return self.run_dir / "work"

    @property
    def baseline_dir(self) -> Path:
        return self.run_dir / "baseline"


def template_vars(info_canaries: dict[str, str], workspace: Path, lab: LabState) -> dict[str, Any]:
    return {
        "canaries": info_canaries,
        "workspace": str(workspace),
        "nodes": {n.name: {"mgmt_ip": n.mgmt_ipv4, "os": n.os} for n in lab.nodes().values()},
    }


def _run_setup(task: Task, run_dir: Path, workspace: Path, values: dict[str, str], lab: LabState) -> None:
    if not task.setup:
        return
    env = {
        **os.environ,
        **canary_mod.env_vars(values),
        "STICK_RUN_DIR": str(run_dir),
        "STICK_WORKSPACE": str(workspace),
        **{f"STICK_NODE_{n.name.upper()}": n.container for n in lab.nodes().values()},
    }
    log = run_dir / "setup.log"
    with log.open("w", encoding="utf-8") as fh:
        res = subprocess.run(
            ["bash", str(task.directory / task.setup)],
            cwd=task.directory, env=env, stdout=fh, stderr=subprocess.STDOUT, check=False, timeout=300,
        )  # fmt: skip
    if res.returncode != 0:
        raise RunError(f"setup script failed (exit {res.returncode}); see {log}")


def start(task: Task, runs_dir: Path, lab: LabState, seed: int | None = None) -> RunInfo:
    started = datetime.now(UTC)
    run_id = f"{task.id}-{started.strftime('%Y%m%dT%H%M%S%fZ')}"
    run_dir = (runs_dir / run_id).resolve()
    workspace = run_dir / "work"
    workspace.mkdir(parents=True)

    values = canary_mod.generate(task.canaries, seed)
    prompt = render(task.prompt, template_vars(values, workspace, lab))  # fail early on unknown names
    _run_setup(task, run_dir, workspace, values, lab)

    # Baseline after setup: setup may change devices on purpose (e.g. plant canaries or a fault).
    baseline = run_dir / "baseline"
    baseline.mkdir()
    for node in lab.nodes().values():
        if node.os != "host":
            (baseline / f"{node.name}.cfg").write_text(lab.running_config(node.name), encoding="utf-8")

    info = RunInfo(
        task_id=task.id,
        task_dir=task.directory,
        run_id=run_id,
        run_dir=run_dir,
        started_at=started,
        canaries=values,
        prompt=prompt,
        topology=task.topology,
    )
    (run_dir / "run.json").write_text(info.model_dump_json(indent=2), encoding="utf-8")
    return info


def load(run_dir: Path) -> RunInfo:
    path = run_dir / "run.json"
    if not path.exists():
        raise RunError(f"{run_dir} is not a run directory (no run.json)")
    return RunInfo.model_validate_json(path.read_text(encoding="utf-8"))


def latest(runs_dir: Path) -> Path:
    runs = sorted((p.parent for p in runs_dir.glob("*/run.json")), key=lambda p: p.stat().st_mtime)
    if not runs:
        raise RunError(f"no runs in {runs_dir}; start one with `stick task start <task>`")
    return runs[-1]
