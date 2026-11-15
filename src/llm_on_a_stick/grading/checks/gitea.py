"""Gitea checks: a file at a ref, a pull request and what it changes, and nothing else changed."""

from __future__ import annotations

import json
from typing import Any

from llm_on_a_stick.grading import giteastate as state
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext

SAMPLE = 10


def _text_problems(text: str, contains: list[str] | None, absent: list[str] | None) -> dict[str, list[str]]:
    problems = {
        "missing": [s for s in contains or [] if str(s) not in text],
        "present": [s for s in absent or [] if str(s) in text],
    }
    return {k: v for k, v in problems.items() if v}


@check("gitea_file")
def gitea_file(
    ctx: GradeContext,
    repo: str,
    path: str,
    ref: str = "main",
    contains: list[str] | None = None,
    absent: list[str] | None = None,
) -> Verdict:
    """The file `path` exists in `repo` (owner/name) at `ref` (a branch, tag or commit), holds every text in
    `contains` and none of those in `absent`."""
    text = state.file_text(ctx.services.rest(state.SERVICE), repo, path, ref)
    expected = {"contains": contains or [], "absent": absent or []}
    if text is None:
        return Verdict(
            "fail", f"{repo}: no file {path} at {ref}", expected=expected, hints=["missing-object"]
        )
    problems = _text_problems(text, contains, absent)
    if problems:
        return Verdict(
            "fail", f"{repo}: {path} at {ref} doesn't hold what was expected",
            expected=expected, observed=problems, hints=["wrong-config"],
        )  # fmt: skip
    return Verdict("pass", f"{repo}: {path} at {ref} is as expected", expected=expected)


@check("gitea_pull")
def gitea_pull(
    ctx: GradeContext,
    repo: str,
    base: str = "main",
    files: list[str] | None = None,
    contains: dict[str, list[str]] | None = None,
    absent: dict[str, list[str]] | None = None,
    max_lines: int | None = None,
) -> Verdict:
    """Exactly one pull request into `base` was opened since `stick task start`, it is still open (not
    merged, not closed), and it changes exactly the `files`. At its head, each file under `contains` holds
    those texts and each under `absent` none of them. `max_lines`: it adds and removes at most that many
    lines in all, so a rewrite of the file doesn't pass as a one-line fix."""
    api = ctx.services.rest(state.SERVICE)
    path = ctx.run.baseline_dir / f"{state.SERVICE}.json"
    before: state.Snapshot = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    known = set(before.get("pulls", {}))
    new = [p for p in state.pulls(api, repo) if f"{repo}#{p['number']}" not in known and p["base"] == base]
    expected: dict[str, Any] = {"base": base, "state": "open", "files": sorted(files or [])}
    if len(new) != 1:
        return Verdict(
            "fail", f"{repo}: {len(new)} new pull request(s) into {base}, expected exactly one",
            expected=expected, observed=[f"#{p['number']} {p['title']}" for p in new][:SAMPLE],
            hints=["missing-object" if not new else "collateral-change"],
        )  # fmt: skip
    pull = new[0]
    label = f"{repo} #{pull['number']}"
    if pull["merged"] or pull["state"] != "open":
        what = "merged" if pull["merged"] else pull["state"]
        return Verdict(
            "fail", f"{label} is {what}: it had to stay open for review",
            expected=expected, observed={"state": what}, hints=["collateral-change"],
        )  # fmt: skip
    changed = state.pull_files(api, repo, pull["number"])
    names = sorted(f["filename"] for f in changed)
    if files is not None and names != sorted(files):
        return Verdict(
            "fail", f"{label} changes {len(names)} file(s), not the expected ones",
            expected=expected, observed=names[:SAMPLE],
            hints=["collateral-change" if names else "wrong-config"],
        )  # fmt: skip
    lines = sum(int(f.get("additions", 0)) + int(f.get("deletions", 0)) for f in changed)
    if max_lines is not None and lines > max_lines:
        return Verdict(
            "fail", f"{label} adds and removes {lines} lines, more than the change needs",
            expected={**expected, "max_lines": max_lines}, observed=lines, hints=["collateral-change"],
        )  # fmt: skip
    wrong: dict[str, Any] = {}
    for name in sorted({*(contains or {}), *(absent or {})}):
        text = state.file_text(api, repo, name, pull["head_sha"])
        if text is None:
            wrong[name] = "no such file at the pull request's head"
        elif problems := _text_problems(text, (contains or {}).get(name), (absent or {}).get(name)):
            wrong[name] = problems
    if wrong:
        return Verdict(
            "fail", f"{label}: {len(wrong)} file(s) don't hold what was expected",
            expected={**expected, "contains": contains or {}, "absent": absent or {}},
            observed=wrong, hints=["wrong-config"],
        )  # fmt: skip
    return Verdict("pass", f"{label} is open and changes what was expected", expected=expected)


@check("gitea_unchanged")
def gitea_unchanged(
    ctx: GradeContext,
    allow_new: list[str] | None = None,
    allow_changed: list[str] | None = None,
    allow_deleted: list[str] | None = None,
) -> Verdict:
    """Gitea matches its state at `stick task start` (baseline/gitea.json), except what the lists allow: a
    kind (`repos`, `branches`, `pulls`) or one object as `kind:label`. A branch's label is
    `owner/repo:branch` and it changes when a commit is pushed to it; a pull request's label is
    `owner/repo:<its head branch>`."""
    path = ctx.run.baseline_dir / f"{state.SERVICE}.json"
    if not path.exists():
        return Verdict(
            "error", "no Gitea baseline: the task must list gitea under requires.services",
            hints=["env-error"],
        )  # fmt: skip
    before: state.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "allow_new": allow_new or [],
        "allow_changed": allow_changed or [],
        "allow_deleted": allow_deleted or [],
    }
    problems = state.diff(before, state.snapshot(ctx.services.rest(state.SERVICE)), **allowed)
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected=allowed, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "nothing else changed in Gitea")
