"""Task discovery and schema validation (`stick task lint`)."""

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
