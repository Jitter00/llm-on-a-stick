"""The result.json model. `stick grade` writes one per attempt."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

CheckStatus = Literal["pass", "fail", "error"]
Outcome = Literal["pass", "partial", "fail", "error"]

# Failure hints a check can attach. The transcript-based classifier (later) adds more,
# e.g. cli-syntax, wrong-dialect, loop, gave-up.
FailureHint = Literal[
    "no-output",  # expected file/artefact missing or empty
    "truncated-output",  # output is a strict subset of what the device has (pager, cut-off)
    "hallucinated-value",  # output contains values the device doesn't have
    "wrong-format",  # output barely overlaps with the expected format
    "incomplete-config",  # device lacks some of the expected configuration
    "wrong-config",  # device state differs from what was asked
    "collateral-change",  # something outside the allowed scope changed
    "missing-object",  # expected object (NetBox, Oxidized backup...) not found
    "env-error",  # the grader or lab failed; not the model's fault
]


class CheckResult(BaseModel):
    name: str
    type: str
    status: CheckStatus
    weight: float = 1.0
    message: str = ""
    expected: Any = None
    observed: Any = None
    hints: list[FailureHint] = Field(default_factory=list)


class Result(BaseModel):
    schema_version: int = SCHEMA_VERSION
    task_id: str
    run_id: str
    stick_version: str
    started_at: datetime
    graded_at: datetime
    outcome: Outcome
    score: float = Field(ge=0, le=1, description="Weighted share of checks that passed (errors excluded).")
    checks: list[CheckResult]
    failure_hints: list[FailureHint] = Field(default_factory=list, description="Union of all check hints.")
    canaries: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Filled in by the runner: tokens, cost, wall time, turns, tool calls.",
    )


def summarise(checks: list[CheckResult]) -> tuple[Outcome, float, list[FailureHint]]:
    """Outcome rules: any check error -> error; otherwise by weighted share of passes."""
    hints: list[FailureHint] = []
    for c in checks:
        hints.extend(h for h in c.hints if h not in hints)
    if any(c.status == "error" for c in checks):
        return "error", 0.0, hints
    total = sum(c.weight for c in checks)
    passed = sum(c.weight for c in checks if c.status == "pass")
    score = round(passed / total, 4) if total else 0.0
    if score == 1.0:
        return "pass", score, hints
    return ("fail" if score == 0.0 else "partial"), score, hints
