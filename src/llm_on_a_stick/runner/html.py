"""The report as one self-contained HTML page (`stick report --html`, and at the end of `stick run`).

The page is data/report.html with the report (runner/report.py: build_report) embedded as JSON; its inline
script builds the page. No template engine, no network: the file opens from disk and can be passed around.
Transcripts hold whatever the lab printed (service API tokens included), all of it lab-only.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from llm_on_a_stick.runner import report

PLACEHOLDER = "__STICK_REPORT_JSON__"


def embed(data: dict[str, Any]) -> str:
    """JSON that is safe inside a <script> element: no `<`, `>` or `&` left for the HTML parser."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for char in ("<", ">", "&", chr(0x2028), chr(0x2029)):
        text = text.replace(char, f"\\u{ord(char):04x}")
    return text


def render(data: dict[str, Any]) -> str:
    template = files("llm_on_a_stick").joinpath("data/report.html").read_text(encoding="utf-8")
    return template.replace(PLACEHOLDER, embed(data))


def slim_json(data: dict[str, Any]) -> str:
    """The report without the transcripts and prompts (those stay in the run folders): report.json."""
    attempts = {
        k: {f: v for f, v in a.items() if f not in ("events", "prompt")} for k, a in data["attempts"].items()
    }
    return json.dumps({**data, "attempts": attempts}, indent=2, ensure_ascii=False) + "\n"


def write(paths: list[Path], out: Path, title: str = "", task: str | None = None) -> dict[str, Any] | None:
    """Write the page for the attempts under `paths`, and report.json next to it. None: no model runs."""
    attempts = report.collect_attempts(paths)
    if task:
        attempts = [a for a in attempts if a.task_id == task]
    if not attempts:
        return None
    data = report.build_report(attempts, title)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    out.with_suffix(".json").write_text(slim_json(data), encoding="utf-8")
    return data
