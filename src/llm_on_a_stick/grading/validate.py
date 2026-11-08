"""Task requirements and `stick task validate`.

A task is only trustworthy if it can be solved and can't be passed by doing nothing:
  1. start a run, execute the task's oracle (reference solution), grade -> must be `pass`
  2. start a fresh run, do nothing, grade -> must be `fail` or `partial` (and never `error`)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llm_on_a_stick import services
from llm_on_a_stick.grading import grade as grade_mod
from llm_on_a_stick.grading import run as run_mod
from llm_on_a_stick.grading.labstate import LabState
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.tasks import Task


def check_requirements(task: Task, lab: LabState) -> list[str]:
    """Problems that would make a run pointless (empty list = fine)."""
    problems = []
    nodes = lab.nodes()
    for device in task.requires.get("devices", []) or []:
        if device not in nodes:
            problems.append(f"needs device {device!r}, which isn't in topology {task.topology!r}")
    for name in task.requires.get("services", []) or []:
        try:
            spec = services.load(name)
        except FileNotFoundError:
            problems.append(f"needs unknown service {name!r}")
            continue
        if not lifecycle.healthy(spec):
            problems.append(f"needs service {name!r} running: `uv run stick svc up {name}`")
    return problems


@dataclass
class Validation:
    task_id: str
    oracle_outcome: str | None
    noop_outcome: str | None
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.problem is None
            and self.oracle_outcome == "pass"
            and self.noop_outcome in ("fail", "partial")
        )


def validate(task: Task, lab: LabState, runs_dir: Path, seed: int | None = None) -> Validation:
    problems = check_requirements(task, lab)
    if problems:
        return Validation(task.id, None, None, "; ".join(problems))
    if not task.oracle:
        return Validation(task.id, None, None, "task has no oracle script")
    try:
        info = run_mod.start(task, runs_dir, lab, seed)
        run_mod.run_oracle(info, task, lab)
        oracle = grade_mod.grade(info.run_dir, lab=lab)
        noop_info = run_mod.start(task, runs_dir, lab, seed)
        noop = grade_mod.grade(noop_info.run_dir, lab=lab)
    except run_mod.RunError as exc:
        return Validation(task.id, None, None, str(exc))
    problem = None
    if oracle.outcome != "pass":
        failed = [f"{c.name}: {c.message}" for c in oracle.checks if c.status != "pass"]
        problem = f"oracle got {oracle.outcome}: {'; '.join(failed)} ({info.run_dir})"
    elif noop.outcome not in ("fail", "partial"):
        problem = f"doing nothing got {noop.outcome}; the checks don't test the task ({noop_info.run_dir})"
    return Validation(task.id, oracle.outcome, noop.outcome, problem)
