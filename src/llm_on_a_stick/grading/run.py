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
from pathlib import Path, PurePath, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from llm_on_a_stick import paths, services
from llm_on_a_stick.grading import canaries as canary_mod
from llm_on_a_stick.grading.labstate import LabState, LabStateError
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


def service_urls() -> dict[str, dict[str, str]]:
    """Base URL of each service as seen from the host, e.g. {"oxidized": {"url": "http://127.0.0.1:8888"}}."""
    urls = {}
    for name in services.available():
        parsed = urlparse(services.load(name).health.url)
        urls[name] = {"url": f"{parsed.scheme}://{parsed.netloc}"}
    return urls


def template_vars(info_canaries: dict[str, str], workspace: PurePath, lab: LabState) -> dict[str, Any]:
    return {
        "canaries": info_canaries,
        "workspace": str(workspace),
        "nodes": {n.name: {"mgmt_ip": n.mgmt_ipv4, "os": n.os} for n in lab.nodes().values()},
        "services": service_urls(),
    }


def script_env(
    task: Task, run_dir: Path, workspace: Path, values: dict[str, str], lab: LabState
) -> dict[str, str]:
    """Environment for a task's setup and oracle scripts."""
    env = {
        **os.environ,
        **canary_mod.env_vars(values),
        "STICK_RUN_DIR": str(run_dir),
        "STICK_WORKSPACE": str(workspace),
        "STICK_TASK_DIR": str(task.directory),
        "STICK_LIB": str(paths.sections_dir() / "_lib"),
    }
    for n in lab.nodes().values():
        env[f"STICK_NODE_{n.name.upper()}"] = n.container
        env[f"STICK_NODE_{n.name.upper()}_IP"] = n.mgmt_ipv4
    return env


def run_script(task: Task, script: str, kind: str, run_dir: Path, env: dict[str, str]) -> None:
    """Run a task script (setup or oracle) with bash, logging to <run dir>/<kind>.log."""
    log = run_dir / f"{kind}.log"
    with log.open("w", encoding="utf-8") as fh:
        res = subprocess.run(
            ["bash", str(task.directory / script)],
            cwd=task.directory, env=env, stdout=fh, stderr=subprocess.STDOUT, check=False, timeout=300,
        )  # fmt: skip
    if res.returncode != 0:
        tail = " | ".join(log.read_text(encoding="utf-8").strip().splitlines()[-3:])
        raise RunError(f"{kind} script failed (exit {res.returncode}): {tail} (full log: {log})")


def run_oracle(info: RunInfo, task: Task, lab: LabState) -> None:
    """Run the task's reference solution against this run (used by `stick task validate`)."""
    if not task.oracle:
        raise RunError(f"task {task.id} has no oracle script")
    env = script_env(task, info.run_dir, info.workspace, info.canaries, lab)
    run_script(task, task.oracle, "oracle", info.run_dir, env)


def start(
    task: Task, runs_dir: Path, lab: LabState, seed: int | None = None, workdir: str | None = None
) -> RunInfo:
    """Create the run folder, canaries, setup and baseline. `workdir`: the workspace path to show in the
    prompt when the agent sees the workspace somewhere else (the runner's toolbox mounts it at /work)."""
    started = datetime.now(UTC)
    run_id = f"{task.id}-{started.strftime('%Y%m%dT%H%M%S%fZ')}"
    run_dir = (runs_dir / run_id).resolve()
    workspace = run_dir / "work"
    workspace.mkdir(parents=True)

    values = canary_mod.generate(task.canaries, seed)
    # workdir is a path inside the (Linux) toolbox container: keep it POSIX, also on Windows hosts.
    shown: PurePath = PurePosixPath(workdir) if workdir else workspace
    prompt = render(task.prompt, template_vars(values, shown, lab))  # fail early on unknown names
    if task.setup:
        run_script(task, task.setup, "setup", run_dir, script_env(task, run_dir, workspace, values, lab))

    # Baseline after setup: setup may change devices on purpose (e.g. plant canaries or a fault).
    baseline = run_dir / "baseline"
    baseline.mkdir()
    for node in lab.nodes().values():
        if node.os != "host":
            try:
                config = lab.running_config(node.name)
            except LabStateError as exc:
                raise RunError(
                    f"cannot read {node.name}: is the lab running? (`stick env up`) [{exc}]"
                ) from exc
            (baseline / f"{node.name}.cfg").write_text(config, encoding="utf-8")

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
