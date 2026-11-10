"""`stick task start`: prepare one attempt at a task.

A run directory holds everything about one attempt:
    run.json       task id, task dir, canaries, rendered prompt, timestamps
    work/          the agent's workspace (files the task asks for go here)
    baseline/      every router's config right after setup (for collateral-change checks), and
                   <service>.json for tasks that need NetBox, Nautobot, LibreNMS, Zabbix or moto (the
                   emulated AWS account)
    restore.log    how long putting each router back to its boot config took
    setup.log      output of the task's setup script, if any
    result.json    written later by `stick grade`
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePath, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from llm_on_a_stick import paths, services
from llm_on_a_stick.grading import awsstate, librenmsstate, sotstate, zabbixstate
from llm_on_a_stick.grading import canaries as canary_mod
from llm_on_a_stick.grading.labstate import LabState, LabStateError
from llm_on_a_stick.grading.template import render
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.lifecycle import ServiceError
from llm_on_a_stick.services.seed import RestClient, RestError
from llm_on_a_stick.tasks import Task


class RunError(RuntimeError):
    pass


def restore_routers(lab: LabState, log: Path) -> None:
    """Every router back to the config the lab booted with: earlier attempts, other tasks and their canaries
    leave nothing behind. The lab itself stays up (a redeploy would take minutes)."""
    lines = []
    for node in lab.nodes().values():
        if node.os == "host":
            continue
        t0 = time.monotonic()
        try:
            lab.restore_config(node.name)
        except LabStateError as exc:
            raise RunError(f"cannot restore {node.name}'s config: is the lab running? [{exc}]") from exc
        lines.append(f"{node.name}: restored to its boot config in {time.monotonic() - t0:.1f}s")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rest_client(name: str) -> RestClient:
    """The REST API client of a source-of-truth service (netbox, nautobot), from its service.yaml."""
    api = services.load(name).api_settings
    if api is None:
        raise RunError(f"{name} service.yaml has no API settings")
    return RestClient(api.base_url, api.headers)


# Per service, how to read the state that `<service>_unchanged` compares later (baseline/<service>.json).
BASELINES: dict[str, Callable[[], Any]] = {
    "netbox": lambda: sotstate.snapshot(rest_client("netbox"), sotstate.ENDPOINTS["netbox"]),
    "nautobot": lambda: sotstate.snapshot(rest_client("nautobot"), sotstate.ENDPOINTS["nautobot"]),
    "librenms": lambda: librenmsstate.snapshot(rest_client("librenms")),
    "zabbix": lambda: zabbixstate.snapshot(rest_client("zabbix")),
    "moto": lambda: awsstate.snapshot(),  # the emulated AWS account, through the toolbox's tools
}


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


def service_vars() -> dict[str, dict[str, str]]:
    """Per service, as seen from the host (and the toolbox, which is on the host network): its base `url`,
    and its API `auth` header and `token` when it has one, e.g.
    {"netbox": {"url": "http://127.0.0.1:8081", "auth": "Bearer nbt_...", "token": "nbt_..."}}.
    """
    out = {}
    for name in services.available():
        spec = services.load(name)
        parsed = urlparse(spec.health.url)
        values = {"url": f"{parsed.scheme}://{parsed.netloc}"}
        headers = spec.api_settings.headers if spec.api_settings else {}
        if auth := headers.get("Authorization", ""):
            values["auth"] = auth
            values["token"] = auth.split(" ", 1)[-1]  # without "Bearer " / "Token "
        elif token := headers.get("X-Auth-Token", ""):  # LibreNMS: the token is the whole header value
            values["token"] = token
        out[name] = values
    return out


def service_env(names: list[str]) -> dict[str, str]:
    """The `env:` of these services' service.yaml: variables that point client tools at them (moto:
    AWS_ENDPOINT_URL, credentials, region). For the toolbox and the scripts of a task that requires them."""
    env: dict[str, str] = {}
    for name in names:
        try:
            env.update(services.load(name).env)
        except FileNotFoundError:  # an unknown service: check_requirements reports it
            continue
    return env


def template_vars(info_canaries: dict[str, str], workspace: PurePath, lab: LabState) -> dict[str, Any]:
    return {
        "canaries": info_canaries,
        "workspace": str(workspace),
        "nodes": {n.name: {"mgmt_ip": n.mgmt_ipv4, "os": n.os} for n in lab.nodes().values()},
        "services": service_vars(),
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
        **service_env(task.requires.get("services") or []),
    }
    for name, values in service_vars().items():  # e.g. STICK_NETBOX_URL, STICK_NETBOX_AUTH
        for key in ("url", "auth"):
            if key in values:
                env[f"STICK_{name.upper()}_{key.upper()}"] = values[key]
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
    for name in task.reset_services:  # back to the seeded snapshot, so every attempt starts the same
        try:
            lifecycle.restore_snapshot(services.load(name))
        except (ServiceError, OSError) as exc:
            raise RunError(f"cannot reset {name}: is it up? (`stick svc up {name}`) [{exc}]") from exc
    restore_routers(lab, run_dir / "restore.log")
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
    for name in task.requires.get("services") or []:  # baseline/<name>.json, for <name>_unchanged
        if name not in BASELINES:
            continue
        try:
            snap = BASELINES[name]()
        except (RestError, awsstate.AwsStateError) as exc:
            raise RunError(f"cannot read {name}: is it up? (`stick svc up {name}`) [{exc}]") from exc
        (baseline / f"{name}.json").write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")

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
