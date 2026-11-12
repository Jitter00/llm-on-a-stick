"""Task discovery, schema validation (`stick task lint`) and loading."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

# The one check type that code doesn't grade: a judge model scores it (grading/judge.py), apart from the rest.
JUDGE_CHECK = "llm_judge"
JUDGE_ARTIFACTS = ("transcript", "reply")  # or a file in the workspace, by its relative path
JUDGE_SCALE = 5


@dataclass
class LintError:
    path: Path
    message: str


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(files("llm_on_a_stick").joinpath("data/task.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def discover(roots: Iterable[Path]) -> list[Path]:
    """Every task.yaml under the given roots (built-in sections and/or user task dirs)."""
    found: list[Path] = []
    for root in roots:
        if root.is_file() and root.name == "task.yaml":
            found.append(root)
        elif root.is_dir():
            found.extend(sorted(root.rglob("task.yaml")))
    return found


def lint_file(path: Path) -> list[LintError]:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [LintError(path, f"cannot read YAML: {exc}")]
    errors = [
        LintError(path, f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}")
        for err in sorted(_validator().iter_errors(data), key=lambda e: list(e.absolute_path))
    ]
    if isinstance(data, dict) and not errors:
        if data.get("id") != path.parent.name:
            errors.append(
                LintError(path, f"id {data.get('id')!r} must match its directory {path.parent.name!r}")
            )
        services_ = (data.get("requires") or {}).get("services") or []
        for name in (data.get("tools") or {}).get("mcp") or []:
            if name not in services_:
                errors.append(LintError(path, f"tools.mcp names {name!r}, which is not in requires.services"))
        checks = [c for c in data.get("checks") or [] if isinstance(c, dict)]
        judged = [c for c in checks if c.get("type") == JUDGE_CHECK]
        if judged and len(judged) == len(checks):
            errors.append(LintError(path, "every check is an llm_judge check: a task needs a code check too"))
        for c in judged:
            errors.extend(LintError(path, f"llm_judge check: {m}") for m in _judge_problems(c.get("params")))
        for key in ("setup", "oracle"):
            if key in data and not (path.parent / data[key]).exists():
                errors.append(LintError(path, f"{key} script {data[key]!r} does not exist"))
    return errors


def _judge_problems(params: Any) -> list[str]:
    params = params if isinstance(params, dict) else {}
    problems = []
    unknown = sorted(set(params) - {"artifact", "rubric", "reference", "scale"})
    if unknown:
        problems.append(f"unknown parameter(s) {', '.join(unknown)}")
    rubric = params.get("rubric")
    if not isinstance(rubric, str) or len(rubric.strip()) < 20:
        problems.append("needs a `rubric` (what each end of the scale means)")
    artifact = params.get("artifact", "transcript")
    if not isinstance(artifact, str) or not artifact.strip():
        problems.append("`artifact` must be transcript, reply or a file in the workspace")
    elif artifact not in JUDGE_ARTIFACTS and (artifact.startswith("/") or ".." in artifact.split("/")):
        problems.append(f"`artifact` {artifact!r} must be a path inside the workspace")
    if "reference" in params and not isinstance(params["reference"], str):
        problems.append("`reference` must be text")
    scale = params.get("scale", JUDGE_SCALE)
    if isinstance(scale, bool) or not isinstance(scale, int) or not 2 <= scale <= 10:
        problems.append("`scale` must be a whole number from 2 to 10")
    return problems


def lint(roots: Iterable[Path]) -> tuple[list[Path], list[LintError]]:
    files_ = discover(roots)
    return files_, [e for f in files_ for e in lint_file(f)]


# --------------------------------------------------------------------------- loading


class TaskError(RuntimeError):
    pass


class CheckSpec(BaseModel):
    type: str
    name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0

    @property
    def label(self) -> str:
        return self.name or self.type


class Task(BaseModel):
    id: str
    section: str
    title: str
    tier: str
    prompt: str
    floor: bool = False
    checks: list[CheckSpec]
    tags: list[str] = Field(default_factory=list)
    topology: str = "base"
    requires: dict[str, Any] = Field(default_factory=dict)
    # What the model works with. Empty: a shell in the toolbox. {"mcp": [services]}: only the tools of those
    # services' MCP servers.
    tools: dict[str, list[str]] = Field(default_factory=dict)
    canaries: dict[str, str] = Field(default_factory=dict)
    setup: str | None = None
    oracle: str | None = None
    allowed_changes: list[str] = Field(default_factory=list)
    reset_services: list[str] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)
    directory: Path = Path()


def load_task(path: Path) -> Task:
    """Load and validate a task.yaml (or a task directory)."""
    path = path / "task.yaml" if path.is_dir() else path
    errors = lint_file(path)
    if errors:
        raise TaskError("; ".join(f"{e.path}: {e.message}" for e in errors))
    task = Task.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    task.directory = path.parent.resolve()
    return task


def find_task(ref: str, roots: Iterable[Path]) -> Task:
    """`ref` is a task id (searched under `roots`) or a path to a task dir / task.yaml."""
    candidate = Path(ref)
    if candidate.exists():
        return load_task(candidate)
    for path in discover(roots):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("id") == ref:
            return load_task(path)
    raise TaskError(f"task {ref!r} not found (searched: {', '.join(str(r) for r in roots)})")
