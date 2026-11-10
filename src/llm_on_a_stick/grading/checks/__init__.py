"""Check registry.

A check is a function `(ctx, **params) -> Verdict`, registered with `@check("name")`. Built-in checks
live in `builtin.py`; extra ones can come from any installed package that declares an entry point in
the `llm_on_a_stick.checks` group (the entry point's module is imported, which registers its checks).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from llm_on_a_stick.grading.context import GradeContext, RestError, ServiceUnavailable
from llm_on_a_stick.grading.labstate import LabStateError
from llm_on_a_stick.grading.results import CheckResult, CheckStatus, FailureHint
from llm_on_a_stick.grading.template import TemplateError, render_value
from llm_on_a_stick.tasks import CheckSpec

ENTRY_POINT_GROUP = "llm_on_a_stick.checks"


@dataclass
class Verdict:
    status: CheckStatus
    message: str = ""
    expected: Any = None
    observed: Any = None
    hints: list[FailureHint] = field(default_factory=list)


CheckFn = Callable[..., Verdict]
_REGISTRY: dict[str, CheckFn] = {}
_loaded = False


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            raise ValueError(f"check {name!r} registered twice")
        _REGISTRY[name] = fn
        return fn

    return register


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from llm_on_a_stick.grading.checks import (  # noqa: F401  (registers built-ins)
        aws,
        builtin,
        librenms,
        netbox,
        retrieval,
        zabbix,
    )

    for ep in entry_points(group=ENTRY_POINT_GROUP):
        ep.load()


def available() -> list[str]:
    _load()
    return sorted(_REGISTRY)


def run_check(spec: CheckSpec, ctx: GradeContext, variables: dict[str, Any]) -> CheckResult:
    _load()

    def error(message: str) -> CheckResult:
        return CheckResult(
            name=spec.label,
            type=spec.type,
            weight=spec.weight,
            status="error",
            message=message,
            hints=["env-error"],
        )

    fn = _REGISTRY.get(spec.type)
    if fn is None:
        return error(f"unknown check type {spec.type!r}")
    try:
        params = render_value(spec.params, variables)
        verdict = fn(ctx, **params)
    except TemplateError as exc:
        return error(f"bad task parameters: {exc}")
    except (TypeError, ValueError) as exc:  # wrong/missing/unsafe parameters: a task-authoring error
        return error(f"bad parameters: {exc}")
    except (LabStateError, RestError, ServiceUnavailable, OSError) as exc:
        return error(f"could not read lab state: {exc}")
    return CheckResult(
        name=spec.label,
        type=spec.type,
        weight=spec.weight,
        status=verdict.status,
        message=verdict.message,
        expected=verdict.expected,
        observed=verdict.observed,
        hints=verdict.hints,
    )
