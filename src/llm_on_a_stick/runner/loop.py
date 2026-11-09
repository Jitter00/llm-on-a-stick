"""`stick run`: one model, one task, one attempt.

    start the task (canaries, setup, baseline) -> toolbox container -> agent loop -> grade -> metrics

Every model gets the same system prompt, the same single tool and the same limits. Everything is recorded in
the run folder: transcript.jsonl (each turn and command), metrics.json, and result.json with `metrics`
filled in.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import psutil
import yaml

from llm_on_a_stick.grading import grade as grade_mod
from llm_on_a_stick.grading import run as run_mod
from llm_on_a_stick.grading import validate as validate_mod
from llm_on_a_stick.grading.labstate import LabState
from llm_on_a_stick.grading.results import FailureHint, Result
from llm_on_a_stick.grading.transcript import transcript_hints
from llm_on_a_stick.runner import toolbox as toolbox_mod
from llm_on_a_stick.runner.models import (
    Client,
    ModelError,
    ToolCall,
    ToolDef,
    ToolResult,
    context_full,
    repeating,
)
from llm_on_a_stick.tasks import Task

# Version 2: the workspace is /work (not a long host path), and the reply is said not to be graded.
# Version 3: shorter (every token is re-read on every turn, which is slow for local models); command output
# is capped at 4000 characters (was 16000).
# Version 4: names the cloud tools (aws, boto3, terraform), added for the aws and terraform sections.
SYSTEM_PROMPT_VERSION = 4
SYSTEM_PROMPT = """\
You are a network engineer in a lab. Your one tool, run_command, runs a bash command (no terminal, \
{cmd_timeout}s timeout) on a Linux toolbox on the lab's management network, with ssh, sshpass, curl, jq, \
python3 + ncclient and boto3, netconf-console2, aws and terraform. Your working directory is {workdir}.

- Nothing can prompt you for input: pass passwords and commands as arguments.
- You see at most {max_output} characters of each command's output: save long output to a file and read \
it with grep, head or sed -n.
- Do only what the task asks. Only what it asks you to produce (files, device configuration) is checked, \
not your reply. When done, reply with a short summary and no tool call.
"""

# One nudge per attempt, the same for every model, when a reply is cut off without a tool call (it hit
# the output-token cap, or was stopped because it kept repeating itself) or is empty (no text, no tool
# call). The next such reply ends the attempt.
NUDGE = (
    "Your last reply was cut off without a tool call: it hit the output limit or kept repeating itself. "
    "Continue: run the next command, or reply with a short summary if you have finished."
)
# Returned instead of running a command from a cut-off reply: it may be incomplete (half a script, an
# unclosed heredoc), and running half a command could do half a change.
CUT_OFF_COMMAND = (
    "error: not run. Your reply was cut off at the output limit while writing this command, so it may be "
    "incomplete. Write shorter commands (build long scripts in a file over several commands)."
)

NUDGE_EMPTY = (
    "Your last reply was empty: no text and no tool call. Continue: run the next command, or reply with a "
    "short summary if you have finished."
)
MAX_NUDGES = 1

RUN_COMMAND = ToolDef(
    name="run_command",
    description="Run a bash command in the toolbox and return its exit code and output (stdout and stderr).",
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string", "description": "The bash command to run."}},
        "required": ["command"],
        "additionalProperties": False,
    },
)


SAFETY_TIMEOUT_S = 3600


@dataclass
class Settings:
    max_turns: int | None = None  # default: the task's limits.turns, else 30
    # The limit is the turns. Time is only a safety net (a hung server, a very slow machine): it depends on
    # the hardware, so it shouldn't decide results. Default: the larger of the task's limits.time_s and
    # SAFETY_TIMEOUT_S.
    timeout_s: int | None = None
    max_tokens: int | None = None  # total tokens read+written; default: the task's limits.tokens (no limit)
    cmd_timeout_s: int = 60
    max_output_chars: int = 4000  # ~1000 tokens, kept in the context for the rest of the attempt
    seed: int | None = None
    min_free_ram_mb: int = 2048  # keep this much RAM for the system; 0 turns the guard off


@dataclass
class Metrics:
    model: str
    provider: str
    base_url: str
    task_id: str
    system_prompt_version: int = SYSTEM_PROMPT_VERSION
    # done | max_turns | timeout | token_limit | model_error | refusal | low_memory | output_limit
    # | empty_reply | context_full
    stop_reason: str = ""
    error: str = ""
    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0  # malformed tool calls (bad JSON, unknown tool)
    command_failures: int = 0  # commands with a non-zero exit code
    command_timeouts: int = 0
    truncated_outputs: int = 0
    output_limit_hits: int = 0  # replies cut off at the output-token cap
    repetition_loops: int = 0  # ...of which were the model repeating itself
    empty_replies: int = 0  # replies with no text and no tool call
    nudges: int = 0  # "continue" messages sent after a cut-off or empty reply
    commands_not_run: int = 0  # commands from cut-off replies, refused because they may be incomplete
    tokens_in: int = 0
    tokens_out: int = 0
    peak_context_tokens: int = 0
    context_window: int | None = None  # what the server allowed, when it says
    cost_usd: float | None = None
    wall_s: float = 0.0
    model_s: float = 0.0
    tools_s: float = 0.0
    sampling: dict[str, Any] = field(default_factory=dict)  # what was sent, e.g. {"temperature": 0.0}
    sampling_source: str = ""  # data/sampling.yaml: <entry> | default | --temperature
    limits: dict[str, Any] = field(default_factory=dict)


@cache
def _prices() -> dict[str, dict[str, float]]:
    data = yaml.safe_load(files("llm_on_a_stick").joinpath("data/prices.yaml").read_text(encoding="utf-8"))
    return {str(k): v for k, v in (data or {}).items()}


def cost(spec: str, local: bool, tokens_in: int, tokens_out: int) -> float | None:
    """USD from data/prices.yaml (per million tokens); 0 for local servers; None when unknown."""
    if local:
        return 0.0
    price = _prices().get(spec)
    if not price:
        return None
    return round(tokens_in * price["input"] / 1e6 + tokens_out * price["output"] / 1e6, 6)


def _hints(m: Metrics) -> list[FailureHint]:
    hints: list[FailureHint] = []
    if m.stop_reason == "max_turns":
        hints.append("max-turns")
    if m.stop_reason in ("timeout", "token_limit"):
        hints.append("timeout")
    if m.stop_reason == "low_memory":
        hints.append("env-error")  # the machine, not the model
    if m.stop_reason == "model_error":
        hints.append("model-error")
    if m.stop_reason == "refusal":
        hints.append("refusal")
    if m.output_limit_hits:
        hints.append("output-limit")
    if m.repetition_loops:
        hints.append("repetition-loop")
    if m.empty_replies:
        hints.append("empty-reply")
    if m.stop_reason == "context_full":
        hints.append("context-full")
    if m.tool_errors:
        hints.append("tool-call-error")
    if m.tool_calls == 0 and m.stop_reason != "model_error":
        hints.append("no-tool-use")
    return hints


def answer_in_reply(reply: str, canaries: dict[str, str]) -> bool:
    """The final reply quotes one of this attempt's random values: the model found the answer (it can only
    know a canary by reading it off the lab) but didn't deliver it where the task asked."""
    return any(len(v) >= 6 and v in reply for v in canaries.values())


def available_ram_mb() -> int:
    return int(psutil.virtual_memory().available // (1024 * 1024))


def wait_for_ram(min_free_mb: int, wait_s: float = 60, step_s: float = 5) -> int:
    """Available RAM in MiB, after waiting up to `wait_s` for it to rise above `min_free_mb`."""
    deadline = time.monotonic() + wait_s
    free = available_ram_mb()
    while free < min_free_mb and time.monotonic() < deadline:
        time.sleep(step_s)
        free = available_ram_mb()
    return free


class Transcript:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.t0 = time.monotonic()

    def write(self, kind: str, **data: Any) -> None:
        entry = {"t": round(time.monotonic() - self.t0, 3), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")


def _run_tool(
    call: ToolCall, box: toolbox_mod.Toolbox, s: Settings, m: Metrics, tr: Transcript
) -> ToolResult:
    m.tool_calls += 1
    command = (call.arguments or {}).get("command")
    if call.name != RUN_COMMAND.name or not isinstance(command, str) or not command.strip():
        m.tool_errors += 1
        problem = (
            f"unknown tool {call.name!r}; the only tool is run_command"
            if call.name != RUN_COMMAND.name
            else 'invalid arguments: expected {"command": "<bash command>"}'
        )
        tr.write("tool_error", id=call.id, name=call.name, arguments=call.raw_arguments, error=problem)
        return ToolResult(call.id, f"error: {problem}", is_error=True)
    res = box.exec(command, s.cmd_timeout_s)
    m.tools_s += res.seconds
    m.command_failures += res.exit_code != 0
    m.command_timeouts += res.timed_out
    m.truncated_outputs += res.truncated
    tr.write(
        "command",
        id=call.id,
        command=command,
        exit_code=res.exit_code,
        seconds=res.seconds,
        timed_out=res.timed_out,
        output_chars=res.output_chars,
        output=res.output,
    )
    note = f" (timed out after {s.cmd_timeout_s}s)" if res.timed_out else ""
    return ToolResult(call.id, f"exit code {res.exit_code}{note}\n{res.output}", is_error=res.exit_code != 0)


def run_task(
    task: Task,
    client: Client,
    lab: LabState,
    runs_dir: Path,
    settings: Settings | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> tuple[run_mod.RunInfo, Result, Metrics]:
    s = settings or Settings()
    problems = validate_mod.check_requirements(task, lab)
    if problems:
        raise run_mod.RunError(f"{task.id}: " + "; ".join(problems))
    max_turns = s.max_turns or task.limits.get("turns", 30)
    timeout_s = s.timeout_s or max(int(task.limits.get("time_s", 0)), SAFETY_TIMEOUT_S)
    max_tokens = s.max_tokens or task.limits.get("tokens")

    info = run_mod.start(task, runs_dir, lab, seed=s.seed, workdir=toolbox_mod.WORKDIR)
    spec = client.spec
    m = Metrics(
        model=spec.spec,
        provider=spec.provider,
        base_url=spec.base_url,
        task_id=task.id,
        limits={
            "turns": max_turns,
            "time_s": timeout_s,
            "tokens": max_tokens,
            "cmd_timeout_s": s.cmd_timeout_s,
            "max_output_chars": s.max_output_chars,
        },
    )
    m.context_window = getattr(client, "context_window", None)
    m.sampling = dict(getattr(client, "sampling", {}))
    m.sampling_source = str(getattr(client, "sampling_source", ""))
    tr = Transcript(info.run_dir / "transcript.jsonl")
    system = SYSTEM_PROMPT.format(
        cmd_timeout=s.cmd_timeout_s, workdir=toolbox_mod.WORKDIR, max_output=s.max_output_chars
    )
    tr.write("start", model=spec.spec, task=task.id, system=system, prompt=info.prompt, limits=m.limits)

    t0 = time.monotonic()
    box_name = f"stick-toolbox-{info.run_id}".lower()[:120]
    final_text = ""
    tool_env = run_mod.service_env(task.requires.get("services") or [])
    with toolbox_mod.Toolbox(info.workspace, box_name, s.max_output_chars, tool_env) as box:
        variables = run_mod.template_vars(info.canaries, PurePosixPath(toolbox_mod.WORKDIR), lab)
        session = client.new_session(system, info.prompt, [RUN_COMMAND], variables)
        while True:
            if m.turns >= max_turns:
                m.stop_reason = "max_turns"
                break
            if time.monotonic() - t0 > timeout_s:
                m.stop_reason = "timeout"
                break
            if max_tokens and m.tokens_in + m.tokens_out >= max_tokens:
                m.stop_reason = "token_limit"
                break
            if s.min_free_ram_mb and (free := wait_for_ram(s.min_free_ram_mb)) < s.min_free_ram_mb:
                m.stop_reason = "low_memory"
                m.error = (
                    f"only {free} MiB RAM free (minimum {s.min_free_ram_mb}): stopped to protect the system"
                )
                tr.write("low_memory", available_mb=free, minimum_mb=s.min_free_ram_mb)
                log(f"  [stopped: {m.error}]")
                break
            try:
                turn = session.step()
            except ModelError as exc:
                m.stop_reason, m.error = "model_error", str(exc)
                tr.write("model_error", error=str(exc))
                break
            m.turns += 1
            m.model_s += turn.seconds
            m.tokens_in += turn.usage.input_tokens
            m.tokens_out += turn.usage.output_tokens
            m.peak_context_tokens = max(
                m.peak_context_tokens, turn.usage.input_tokens + turn.usage.output_tokens
            )
            tr.write(
                "turn",
                n=m.turns,
                text=turn.text,
                reasoning=turn.reasoning,
                stop_reason=turn.stop_reason,
                tool_calls=[asdict(c) for c in turn.tool_calls],
                usage=asdict(turn.usage),
                usage_estimated=turn.usage_estimated,
                seconds=round(turn.seconds, 3),
            )
            log(f"  turn {m.turns}: {len(turn.tool_calls)} command(s)")
            if context_full(turn, m.context_window):
                m.stop_reason = "context_full"
                tr.write("context_full", n=m.turns, input_tokens=turn.usage.input_tokens)
                log(f"  [stopped: the conversation filled the {m.context_window}-token context window]")
                break
            if turn.cut_off:
                m.output_limit_hits += 1
                looped = repeating(f"{turn.reasoning}\n{turn.text}")
                m.repetition_loops += looped
                tr.write("output_limit", n=m.turns, output_tokens=turn.usage.output_tokens, repetition=looped)
                why = (
                    "stopped: it was repeating itself"
                    if turn.stop_reason == "repetition"
                    else (f"cut off at the output limit{' (repetition loop)' if looped else ''}")
                )
                log(f"  [reply {why}]")
            if not turn.tool_calls:
                final_text = turn.text
                empty = not turn.cut_off and not turn.text.strip() and turn.stop_reason != "refusal"
                if empty:
                    m.empty_replies += 1
                    tr.write("empty_reply", n=m.turns)
                    log("  [empty reply: no text, no command]")
                if (turn.cut_off or empty) and m.nudges < MAX_NUDGES:
                    m.nudges += 1
                    message = NUDGE if turn.cut_off else NUDGE_EMPTY
                    session.add_message(message)
                    tr.write("nudge", n=m.turns, message=message)
                    continue
                if turn.cut_off:
                    m.stop_reason = "output_limit"
                elif empty:
                    m.stop_reason = "empty_reply"
                else:
                    m.stop_reason = "refusal" if turn.stop_reason == "refusal" else "done"
                break
            if turn.cut_off:  # the commands may be incomplete: don't run them, say why
                m.tool_calls += len(turn.tool_calls)
                m.commands_not_run += len(turn.tool_calls)
                for c in turn.tool_calls:
                    tr.write(
                        "command_not_run", id=c.id, reason="cut off", arguments_chars=len(c.raw_arguments)
                    )
                session.add_results(
                    [ToolResult(c.id, CUT_OFF_COMMAND, is_error=True) for c in turn.tool_calls]
                )
                continue
            session.add_results([_run_tool(c, box, s, m, tr) for c in turn.tool_calls])
    m.wall_s = round(time.monotonic() - t0, 3)
    m.model_s, m.tools_s = round(m.model_s, 3), round(m.tools_s, 3)
    m.cost_usd = cost(spec.spec, spec.endpoint.local, m.tokens_in, m.tokens_out)

    result = grade_mod.grade(info.run_dir, lab=lab)
    hints = _hints(m)
    if "no-output" in result.failure_hints and answer_in_reply(final_text, info.canaries):
        hints.append("answer-in-reply")
    hints += transcript_hints(info.run_dir, m.stop_reason)  # hints only: outcome and score stay as graded
    for h in hints:
        if h not in result.failure_hints:
            result.failure_hints.append(h)
    result.metrics = asdict(m)
    (info.run_dir / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (info.run_dir / "metrics.json").write_text(json.dumps(asdict(m), indent=2), encoding="utf-8")
    tr.write(
        "end",
        stop_reason=m.stop_reason,
        outcome=result.outcome,
        score=result.score,
        finished_at=datetime.now(UTC).isoformat(),
    )
    return info, result, m
