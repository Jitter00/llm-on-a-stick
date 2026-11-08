"""`stick grade`: run a task's checks for one run directory and write result.json."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from llm_on_a_stick import __version__
from llm_on_a_stick.grading import run as run_mod
from llm_on_a_stick.grading.checks import run_check
from llm_on_a_stick.grading.context import GradeContext, Services
from llm_on_a_stick.grading.labstate import DockerLabState, LabState
from llm_on_a_stick.grading.results import Result, summarise
from llm_on_a_stick.tasks import load_task


def grade(run_dir: Path, lab: LabState | None = None, services: Services | None = None) -> Result:
    info = run_mod.load(run_dir)
    task = load_task(info.task_dir)
    lab = lab or DockerLabState(info.topology)
    ctx = GradeContext(run=info, lab=lab, services=services or Services())
    variables = run_mod.template_vars(info.canaries, info.workspace, lab)

    results = [run_check(spec, ctx, variables) for spec in task.checks]
    outcome, score, hints = summarise(results)
    result = Result(
        task_id=info.task_id,
        run_id=info.run_id,
        stick_version=__version__,
        started_at=info.started_at,
        graded_at=datetime.now(UTC),
        outcome=outcome,
        score=score,
        checks=results,
        failure_hints=hints,
        canaries=info.canaries,
    )
    (run_dir / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
