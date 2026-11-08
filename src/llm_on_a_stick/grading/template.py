"""Tiny `{{ dotted.name }}` templating for prompts and check parameters.

Deliberately minimal (no loops, no filters): task files stay readable, and an unknown name is an
error at `stick task start` time instead of a silently empty prompt.
"""

from __future__ import annotations

import re
from typing import Any

_VAR = re.compile(r"\{\{\s*([A-Za-z_][\w.-]*)\s*\}\}")


class TemplateError(ValueError):
    pass


def _lookup(name: str, variables: dict[str, Any]) -> Any:
    value: Any = variables
    for part in name.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise TemplateError(f"unknown template variable {{{{ {name} }}}}")
    return value


def render(template: str, variables: dict[str, Any]) -> str:
    return _VAR.sub(lambda m: str(_lookup(m.group(1), variables)), template)


def render_value(value: Any, variables: dict[str, Any]) -> Any:
    """Render every string inside lists/dicts. A string that is exactly one `{{ x }}` keeps x's type."""
    if isinstance(value, str):
        whole = _VAR.fullmatch(value.strip())
        return _lookup(whole.group(1), variables) if whole else render(value, variables)
    if isinstance(value, list):
        return [render_value(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: render_value(v, variables) for k, v in value.items()}
    return value
