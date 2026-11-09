"""Which lab tests a change needs: CI runs only the sections a pull request touches.

Validating every task of every section takes minutes per task on a CI runner, so a PR gets:

- every task of a **section** whose folder it changes (`sections/<section>/...`), or that requires a
  **service** it changes (`services/<name>/...`, `tests/integration/test_<name>.py`), plus that service's own
  lab tests;
- for a change to **shared code** (`src/`, `sections/_lib/`, topologies, router configs, images, the lab
  tests' helpers, dependencies...): the generic lab tests and each section's **floor** task (`floor: true`),
  enough to catch broken plumbing without validating everything;
- nothing for docs, unit tests and other files that the lab doesn't use.

`python -m llm_on_a_stick.labselect <base> <head>` prints the selection as `STICK_LAB_*` variables, which the
lab tests' conftest reads. With `STICK_LAB_SECTIONS` unset, every lab test runs (the local default).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from llm_on_a_stick import paths, services, tasks

# Files the lab tests never read: changing only these runs no lab test.
_NOT_LAB = ("docs/", "site/", "dist/", "runs/", ".github/ISSUE_TEMPLATE/")
_NOT_LAB_FILES = {
    "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "TODO.md", "LICENSE", "mkdocs.yml",
    "commitlint.config.mjs", "release-please-config.json", ".release-please-manifest.json",
    ".pre-commit-config.yaml", ".gitignore", ".editorconfig", ".yamllint.yaml", ".shellcheckrc",
    "sections/README.md", ".github/pull_request_template.md", ".github/workflows/ci-push.yml",
    ".github/workflows/release.yml", ".github/workflows/_lint.yml", ".github/workflows/_test.yml",
    ".github/scripts/release-only.sh",
}  # fmt: skip


@dataclass
class Selection:
    sections: set[str] = field(default_factory=set)  # every task of these sections
    services: set[str] = field(default_factory=set)  # these services' own lab tests
    core: bool = False  # the generic lab tests and every section's floor task

    @property
    def empty(self) -> bool:
        return not (self.sections or self.services or self.core)

    def env(self) -> dict[str, str]:
        return {
            "STICK_LAB_SECTIONS": ",".join(sorted(self.sections)),
            "STICK_LAB_SERVICES": ",".join(sorted(self.services)),
            "STICK_LAB_CORE": "1" if self.core else "0",
        }

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Selection | None:
        """The selection in `env`, or None (run everything) when STICK_LAB_SECTIONS isn't set."""
        if "STICK_LAB_SECTIONS" not in env:
            return None

        def names(key: str) -> set[str]:
            return {n.strip() for n in env.get(key, "").split(",") if n.strip()}

        return cls(names("STICK_LAB_SECTIONS"), names("STICK_LAB_SERVICES"), env.get("STICK_LAB_CORE") == "1")


def section_services(task_list: Iterable[tasks.Task]) -> dict[str, set[str]]:
    """Section -> the services its tasks require."""
    out: dict[str, set[str]] = {}
    for task in task_list:
        out.setdefault(task.section, set()).update(task.requires.get("services") or [])
    return out


def select(
    changed: Iterable[str], task_list: Iterable[tasks.Task], service_names: Iterable[str]
) -> Selection:
    """The lab tests needed for a change to the files `changed` (repo-relative POSIX paths)."""
    needs = section_services(task_list)
    known_services = set(service_names)
    sel = Selection()

    def add_service(name: str) -> None:
        sel.services.add(name)
        sel.sections.update(s for s, svcs in needs.items() if name in svcs)

    for path in changed:
        parts = PurePosixPath(path).parts
        if path in _NOT_LAB_FILES or path.startswith(_NOT_LAB):
            continue
        if parts[0] == "sections" and len(parts) > 2 and parts[1] != "_lib":
            if parts[1] in needs:  # a deleted section has nothing left to test
                sel.sections.add(parts[1])
            continue
        if parts[0] == "services" and len(parts) > 2:
            if parts[1] in known_services:
                add_service(parts[1])
            continue
        if parts[0] == "tests" and len(parts) == 2:  # unit tests (tests/integration/ is deeper)
            continue
        name = PurePosixPath(path).stem.removeprefix("test_")
        if parts[:2] == ("tests", "integration") and name in known_services:
            add_service(name)
            continue
        sel.core = True  # src/, sections/_lib/, topologies, configs, images, dependencies, CI, the rest
    sel.services.update(svc for s in sel.sections for svc in needs.get(s, set()))
    return sel


def changed_files(base: str, head: str, cwd: Path | None = None) -> list[str]:
    argv = ["git", "diff", "--name-only", f"{base}...{head}"]
    out = subprocess.run(argv, capture_output=True, text=True, check=True, cwd=cwd).stdout
    return [line for line in out.splitlines() if line]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m llm_on_a_stick.labselect <base sha> <head sha>", file=sys.stderr)
        return 2
    task_list = [tasks.load_task(p) for p in tasks.discover([paths.sections_dir()])]
    files = changed_files(argv[0], argv[1])
    sel = select(files, task_list, services.available())
    for key, value in sel.env().items():
        print(f"{key}={value}")
    print(f"run={'false' if sel.empty else 'true'}")
    if sel.empty:
        summary = "none (nothing the lab uses changed)"
    else:
        summary = (
            f"sections: {', '.join(sorted(sel.sections)) or '-'}; "
            f"services: {', '.join(sorted(sel.services)) or '-'}; shared code: {'yes' if sel.core else 'no'}"
        )
    print(f"lab tests for {len(files)} changed file(s): {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["Selection", "changed_files", "section_services", "select"]
