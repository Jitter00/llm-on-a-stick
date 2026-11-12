"""The result.json model. `stick grade` writes one per attempt."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

CheckStatus = Literal["pass", "fail", "error"]
Outcome = Literal["pass", "partial", "fail", "error"]

# Failure hints: checks attach the first group; the runner adds the second from the transcript.
FailureHint = Literal[
    "no-output",  # expected file/artefact missing or empty
    "truncated-output",  # output is a strict subset of what the device has (pager, cut-off)
    "hallucinated-value",  # output contains values the device doesn't have
    "wrong-format",  # output barely overlaps with the expected format
    "unfiltered-output",  # asked for one part, got more (e.g. the whole config instead of the BGP section)
    "incomplete-config",  # device lacks some of the expected configuration
    "wrong-config",  # device state differs from what was asked
    "collateral-change",  # something outside the allowed scope changed
    "missing-object",  # expected object (NetBox, Oxidized backup...) not found
    "env-error",  # the grader or lab failed; not the model's fault
    # Added by the runner from the transcript (`stick run`):
    "max-turns",  # the model was still working when it ran out of turns
    "timeout",  # the run hit its token limit or the safety time limit
    "model-error",  # the model server failed (HTTP error, unreachable); not a task failure as such
    "refusal",  # the model declined the task
    "tool-call-error",  # malformed tool calls (invalid JSON arguments, unknown tool)
    "no-tool-use",  # the model answered without running a single command
    "output-limit",  # a reply hit the output-token cap (the model got one nudge to continue)
    "repetition-loop",  # ...and the cut-off reply was the model repeating itself
    "empty-reply",  # a reply with no text and no tool call (the model got one nudge to continue)
    "context-full",  # the conversation filled the model's context window; the attempt ended there
    "answer-in-reply",  # no output, but the final reply quotes this attempt's canary: found, not delivered
    # From what the model did (grading/transcript.py); hints only, also on passed attempts:
    "wrong-dialect",  # another OS's CLI syntax sent to a node, and the node rejected it
    "attempted-change",  # config-mode commands sent to a node the task says must not change
    "no-verification",  # an output file was written and never read back afterwards
    "ignored-error",  # an output file holds an error (or its last write failed), yet the model finished
]

# The same hints in plain language, for reports.
HINT_TEXT: dict[str, str] = {
    "no-output": "an expected file or artefact was missing or empty",
    "truncated-output": "the output is only part of what the device has (pager, cut-off)",
    "hallucinated-value": "the output contains values the device doesn't have",
    "wrong-format": "the output barely matches the expected format",
    "unfiltered-output": "asked for one part, delivered more (e.g. the whole config)",
    "incomplete-config": "the device lacks some of the expected configuration",
    "wrong-config": "the resulting state differs from what was asked",
    "collateral-change": "something outside the allowed scope was changed",
    "missing-object": "an expected object was not found",
    "env-error": "the grader or the lab failed; not the model's fault",
    "max-turns": "still working when it ran out of turns",
    "timeout": "hit the token limit or the safety time limit",
    "model-error": "the model server failed (HTTP error, unreachable)",
    "refusal": "the model declined the task",
    "tool-call-error": "malformed tool calls (invalid JSON arguments, unknown tool)",
    "no-tool-use": "answered without running a single command",
    "output-limit": "a reply hit the output-token cap",
    "repetition-loop": "a reply was cut off while the model repeated itself",
    "empty-reply": "a reply had no text and no tool call",
    "context-full": "the conversation filled the model's context window",
    "answer-in-reply": "found the answer and put it in the reply instead of delivering it",
    "wrong-dialect": "kept sending another OS's CLI syntax to a node",
    "attempted-change": "sent config-mode commands to a node that must not change",
    "no-verification": "wrote an output file and never read it back",
    "ignored-error": "finished although an output file holds an error",
}


class CheckResult(BaseModel):
    name: str
    type: str
    status: CheckStatus
    weight: float = 1.0
    message: str = ""
    expected: Any = None
    observed: Any = None
    hints: list[FailureHint] = Field(default_factory=list)


# What a judge model says: kept apart from the code checks, and never part of `outcome` or `score`.
JudgeStatus = Literal["graded", "not-graded", "error"]


class JudgeCheck(BaseModel):
    name: str
    status: JudgeStatus = "not-graded"
    artifact: str = "transcript"  # what was judged: transcript, reply, or a file in the workspace
    scale: int = 5  # scores run from 1 (worst) to this
    score: int | None = Field(default=None, description="The median of `scores`.")
    scores: list[int] = Field(default_factory=list, description="One per repeat of the judgement.")
    agreement: float | None = Field(
        default=None, description="Share of the repeats that gave the most common score (1.0: all agreed)."
    )
    reason: str = Field(default="", description="The judge's reason, or why the check was not graded.")


class Judgement(BaseModel):
    model: str | None = Field(default=None, description="The judge, provider/model. None: no judge has run.")
    sampling: dict[str, Any] = Field(default_factory=dict, description="Sampling settings sent to the judge.")
    repeats: int = 0
    checks: list[JudgeCheck] = Field(default_factory=list)
    score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Mean of the graded checks, each put on 0..1. Not part of `score`.",
    )
    summary: str = Field(
        default="",
        description="Why the attempt did not pass, in plain language. Not scored; empty on a pass.",
    )
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    judged_at: datetime | None = None


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
    judge: Judgement | None = Field(
        default=None,
        description="The task's `llm_judge` checks and the failure summary. None: the task has no judge "
        "check and no judge has run. Never changes `outcome` or `score`.",
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
