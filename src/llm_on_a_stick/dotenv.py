"""Read settings from a local ``.env`` file (see ``.env.example``).

Only ``KEY=VALUE`` lines: ``#`` comments, an optional ``export`` and simple quotes are understood,
nothing is expanded. A variable already set in the environment always wins over the file.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if not _NAME.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()  # trailing comment
        out[key] = value
    return out


def load(path: Path, env: MutableMapping[str, str] | None = None) -> list[str]:
    """Set the file's variables that the environment doesn't have yet; return their names.

    A missing or unreadable file is not an error: the result is empty.
    """
    env = os.environ if env is None else env
    try:
        values = parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []
    added = [k for k in values if k not in env]
    for key in added:
        env[key] = values[key]
    return added
