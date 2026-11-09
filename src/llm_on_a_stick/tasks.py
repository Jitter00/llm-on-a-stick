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
        for key in ("setup", "oracle"):
            if key in data and not (path.parent / data[key]).exists():
                errors.append(LintError(path, f"{key} script {data[key]!r} does not exist"))
    return errors


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
