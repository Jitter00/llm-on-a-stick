"""Failure hints from what the model did: rules over an attempt's transcript.jsonl.

These are code, not a judge (see the grading policy in docs/grading.md), and they are **hints only**: they
never change `outcome` or `score`, and passed attempts can carry them too ("passed, but never checked its
output").

    wrong-dialect     another OS's CLI syntax sent to a node and rejected, more than once (a single probe that
                      the model then corrects is normal exploration, not a dialect problem)
    attempted-change  config-mode commands sent to a node the task says must not change
    no-verification   an output file the task checks was written and never read back afterwards; through
                      MCP servers: something was changed and nothing was read after the last change
    ignored-error     an output file holds an error message, or the last command writing it failed, and the
                      model said it had finished; through MCP servers: the last change failed and the model
                      said it had finished

Everything comes from the run folder (transcript.jsonl, run.json, the task's checks and workspace), so the
rules also work on old runs: `stick hints <run dir>...`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

from llm_on_a_stick.grading.labstate import LabStateError, NodeOS, load_nodes
from llm_on_a_stick.grading.results import FailureHint
from llm_on_a_stick.tasks import Task, TaskError, load_task

# Device replies that mean "I didn't understand that command".
REJECTED: dict[str, re.Pattern[str]] = {
    "srlinux": re.compile(r"Parsing error|Unknown token|Unknown command|Error: Path .* is not valid"),
    "frr": re.compile(r"% Unknown command|% Command incomplete|% Ambiguous command|% Invalid input"),
}
# Syntax from another OS (FRR/IOS/Junos on SR Linux; SR Linux/Junos on FRR), matched on the remote command.
FOREIGN: dict[str, re.Pattern[str]] = {
    "srlinux": re.compile(
        r"\bshow\s+(running-config|run\b|configuration|ip\s|bgp\s|interfaces?\s+(brief|status)\b)"
        r"|\bconf(igure)?\s+t(erminal)?\b|\bwrite\s+mem|\bvtysh\b"
    ),
    "frr": re.compile(
        r"^\s*info\b|\benter\s+candidate\b|\bshow\s+/|\binfo\s+flat\b|\bdisplay\s+set\b|\bsr_cli\b"
    ),
}
# A model that tries `show running-config` on SR Linux once and then switches to `info` is exploring; one
# that keeps sending foreign syntax doesn't know the OS. In the first comparison every Strata attempt had at
# most one rejected command, gemma up to five.
DIALECT_MIN_REJECTIONS = 2
# Config-mode commands, on any OS. NETCONF ones are matched on the whole command (ncclient, netconf-console2).
CHANGE = re.compile(
    r"\benter\s+candidate\b|\bcommit\s+(now|stay|validate|save)\b|\bconf(igure)?\s+t(erminal)?\b"
    r"|\bwrite\s+mem(ory)?\b|\bcopy\s+running-config\s+startup-config\b"
)
NETCONF_CHANGE = re.compile(r"<edit-config\b|\bedit_config\s*\(|<commit\s*/>|\.commit\s*\(|--edit-config\b")
# Errors in a command's output (device, NETCONF, shell, Python).
ERROR = re.compile(
    r"Parsing error|Unknown token|% Unknown command|% Command incomplete|<rpc-error>|rpc-error|"
    r"Permission denied|Connection refused|Connection timed out|command not found|"
    r"Traceback \(most recent call last\)|No such file or directory|^Error:",
    re.M,
)

# MCP tools that change something, by name (`device_add`, `rest_update`, `maintenance_create`...), and AWS
# CLI operations that don't.
TOOL_WRITE = re.compile(r"(?:^|_)(create|update|delete|add|edit|remove|set|discover)(?:_|$)")
AWS_READ = re.compile(r"(describe|get|list|search|lookup|filter|wait|help)\b", re.I)

IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
# Quoted search patterns: `grep 'commit'` is not a commit.
SEARCH_ARG = re.compile(r"""\b(e?grep|sed|awk)\b((?:\s+-[-\w=]+)*)\s+(['"]).*?\3""", re.S)
# What a remote command looks like after `ssh ... user@ip`.
REMOTE = re.compile(r"@(\d{1,3}(?:\.\d{1,3}){3})\s+(['\"])(.*?)\2", re.S)


@dataclass
class Command:
    text: str
    output: str
    exit_code: int | None
    timed_out: bool


@dataclass
class ToolUse:
    """One call to an MCP server's tool."""

    tool: str
    arguments: dict[str, Any]
    failed: bool  # the server reported an error, or the call timed out

    @property
    def writes(self) -> bool:
        if self.tool == "call_aws":  # one AWS CLI command: `aws <service> <operation> ...`
            words = str(self.arguments.get("cli_command", "")).split()
            return len(words) > 2 and not AWS_READ.match(words[2])
        return bool(TOOL_WRITE.search(self.tool))


@dataclass
class Attempt:
    """What the rules need from a run folder."""

    commands: list[Command]
    stop_reason: str | None
    nodes: dict[str, tuple[str, NodeOS]] = field(default_factory=dict)  # ip -> (name, os)
    outputs: list[str] = field(default_factory=list)  # workspace-relative files the checks read
    may_change: set[str] | None = None  # nodes the task lets the model change (None: no such rule)
    workspace: Path | None = None
    calls: list[ToolUse] = field(default_factory=list)  # MCP tool calls, in order (no shell in that mode)


# --------------------------------------------------------------------------- loading


def load_attempt(run_dir: Path) -> Attempt:
    commands: list[Command] = []
    calls: list[ToolUse] = []
    stop_reason: str | None = None
    tr = run_dir / "transcript.jsonl"
    if tr.exists():
        for line in tr.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("kind") == "command":
                commands.append(
                    Command(
                        e.get("command", ""),
                        e.get("output", "") or "",
                        e.get("exit_code"),
                        bool(e.get("timed_out")),
                    )
                )
            elif e.get("kind") == "tool_call":
                failed = bool(e.get("is_error") or e.get("timed_out"))
                calls.append(ToolUse(e.get("tool", ""), e.get("arguments") or {}, failed))
            elif e.get("kind") == "end":
                stop_reason = e.get("stop_reason")
    if stop_reason is None and (run_dir / "metrics.json").exists():
        stop_reason = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8")).get("stop_reason")

    run: dict[str, Any] = {}
    if (run_dir / "run.json").exists():
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    nodes: dict[str, tuple[str, NodeOS]] = {}
    try:
        for n in load_nodes(run.get("topology") or "base").values():
            if n.mgmt_ipv4 and n.os != "host":
                nodes[n.mgmt_ipv4] = (n.name, n.os)
    except (LabStateError, OSError, KeyError):
        pass

    task: Task | None = None
    if run.get("task_dir"):
        try:
            task = load_task(Path(run["task_dir"]))
        except (TaskError, OSError):
            task = None  # the task was removed or moved: the file rules are skipped
    outputs, may_change = _from_task(task)
    workspace = run_dir / "work"
    return Attempt(
        commands, stop_reason, nodes, outputs, may_change, workspace if workspace.is_dir() else None, calls
    )


def _from_task(task: Task | None) -> tuple[list[str], set[str] | None]:
    if task is None:
        return [], None
    outputs: list[str] = []
    may_change: set[str] | None = None
    for c in task.checks:
        path = c.params.get("path")
        if isinstance(path, str) and "{{" not in path:
            outputs.append(path)
        if c.type == "no_change_outside":
            may_change = set(c.params.get("allowed") or [])
    return list(dict.fromkeys(outputs)), may_change


# --------------------------------------------------------------------------- rules


def _strip_searches(text: str) -> str:
    return SEARCH_ARG.sub(" ", text)


def _remote_commands(cmd: str, nodes: dict[str, tuple[str, NodeOS]]) -> Iterable[tuple[str, NodeOS, str]]:
    """(node, os, remote command) for each `ssh user@ip '<command>'` and `printf '...' | ssh user@ip`."""
    for m in REMOTE.finditer(cmd):
        if m.group(1) in nodes:
            name, os_ = nodes[m.group(1)]
            yield name, os_, m.group(3)
    for segment in re.split(r"\s*(?:;|&&|\|\|)\s*", cmd):
        if "|" not in segment or ("printf" not in segment and "echo" not in segment):
            continue
        ips = [ip for ip in IP.findall(segment) if ip in nodes]
        if ips and re.search(r"\bssh\b", segment):
            name, os_ = nodes[ips[0]]
            piped = segment.split("|")[0]
            yield name, os_, piped.replace("\\n", "\n")


def wrong_dialect(a: Attempt) -> bool:
    rejected = 0
    for c in a.commands:
        if any(
            FOREIGN[os_].search(line) and REJECTED[os_].search(c.output)
            for _, os_, remote in _remote_commands(c.text, a.nodes)
            for line in remote.splitlines() or [remote]
        ):
            rejected += 1
    return rejected >= DIALECT_MIN_REJECTIONS


def _frozen(a: Attempt, node: str) -> bool:
    return a.may_change is not None and node not in a.may_change


def attempted_change(a: Attempt) -> bool:
    if a.may_change is None:
        return False
    for c in a.commands:
        text = _strip_searches(c.text)
        for node, _, remote in _remote_commands(text, a.nodes):
            if _frozen(a, node) and CHANGE.search(remote):
                return True
        if NETCONF_CHANGE.search(text):
            targets = [a.nodes[ip][0] for ip in IP.findall(text) if ip in a.nodes]
            if not targets or any(_frozen(a, t) for t in targets):
                return True
    return False


def _file_pattern(name: str) -> str:
    return r"(?<![\w.\-/])(?:\./|/work/)?" + re.escape(name) + r"(?![\w.\-])"


def _mentions(cmd: str, path: str) -> list[tuple[int, str]]:
    """Positions of `path` in `cmd`, each tagged "write" or "read", in order."""
    name = PurePosixPath(path).as_posix()
    found: list[tuple[int, str]] = []
    for m in re.finditer(_file_pattern(name), cmd):
        before = cmd[max(0, m.start() - 40) : m.start()]
        after = cmd[m.end() : m.end() + 12]
        write = bool(
            re.search(r"(?:>>?|\btee(?:\s+-a)?|\s-o|--output)\s*['\"]?$", before)
            or re.search(r"\bsed\s+-i\S*\s+(?:'[^']*'|\"[^\"]*\"|\S+)\s+['\"]?$", before)
            or (re.search(r"open\(\s*['\"]?$", before) and re.match(r"['\"]?\s*,\s*['\"][wa]", after))
        )
        found.append((m.start(), "write" if write else "read"))
    # Globs: `ls -l /work/*.cfg`, `cat *.json` read the file too.
    for g in re.finditer(r"(?:/work/)?([\w.\-]*\*[\w.\-*]*)", cmd):
        if fnmatch(name, g.group(1)):
            found.append((g.start(), "read"))
    return sorted(found)


def _last_writes(a: Attempt) -> dict[str, tuple[int, bool]]:
    """For each output file: index of the last command writing it, and whether it was read back after that."""
    state: dict[str, tuple[int, bool]] = {}
    for i, c in enumerate(a.commands):
        for path in a.outputs:
            for _, kind in _mentions(c.text, path):
                if kind == "write":
                    state[path] = (i, False)
                elif path in state:
                    state[path] = (state[path][0], True)
    return state


def _delivered(a: Attempt, path: str) -> bool:
    """The file is in the workspace and not empty (if not, `no-output` already says so)."""
    if a.workspace is None:
        return True  # no workspace to look at: trust the transcript
    f = a.workspace / path
    return f.is_file() and f.stat().st_size > 0


def _last_change(a: Attempt) -> int | None:
    """Index of the last MCP tool call that changes something, if any."""
    return max((i for i, c in enumerate(a.calls) if c.writes), default=None)


def no_verification(a: Attempt) -> bool:
    last = _last_change(a)
    if last is not None and not a.calls[last].failed and len(a.calls) == last + 1:
        return True  # changed something through a tool and looked at nothing afterwards
    return any(not verified and _delivered(a, path) for path, (_, verified) in _last_writes(a).items())


def ignored_error(a: Attempt) -> bool:
    if a.stop_reason != "done":
        return False  # it didn't claim to have finished
    last_change = _last_change(a)
    if last_change is not None and a.calls[last_change].failed:
        return True
    for path, (i, _) in _last_writes(a).items():
        last = a.commands[i]
        if last.timed_out or ERROR.search(last.output):
            return True
        if a.workspace is not None:
            f = a.workspace / path
            try:
                if f.is_file() and ERROR.search(f.read_text(encoding="utf-8", errors="replace")[:200_000]):
                    return True
            except OSError:
                pass
    return False


RULES: list[tuple[FailureHint, Any]] = [
    ("wrong-dialect", wrong_dialect),
    ("attempted-change", attempted_change),
    ("no-verification", no_verification),
    ("ignored-error", ignored_error),
]


def hints_for(a: Attempt) -> list[FailureHint]:
    return [hint for hint, rule in RULES if rule(a)]


def transcript_hints(run_dir: Path, stop_reason: str | None = None) -> list[FailureHint]:
    """The transcript hints of one attempt's run folder (empty if it has no transcript). `stop_reason` is for
    the runner, which asks before it writes the transcript's `end` entry."""
    a = load_attempt(run_dir)
    if stop_reason is not None:
        a.stop_reason = stop_reason
    return hints_for(a)
