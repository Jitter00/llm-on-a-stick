"""Unit tests for the Gitea section: the service definition, the files snapshot, the state and the checks.

No Docker: the API is a fake.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import lab, paths, services
from llm_on_a_stick.grading import giteastate as state
from llm_on_a_stick.grading import run
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.seed import RestError
from llm_on_a_stick.services.spec import FilesSnapshot
from llm_on_a_stick.tasks import load_task
from test_grading import FakeLab, check, make_ctx

REPO = "netops/lab-configs"
TASK = paths.sections_dir() / "gitea" / "gitea-file-at-ref"


class FakeGitea:
    """The parts of /api/v1 the grader reads: one repository, its branches (name -> files), its pulls."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, str]] = {"main": {"intended/srl2.yaml": "description: old\n"}}
        self.pulls: list[dict[str, Any]] = []
        self.changed: dict[int, list[dict[str, Any]]] = {}

    def sha(self, branch: str) -> str:
        return "sha-" + base64.b16encode(json.dumps([branch, self.files[branch]]).encode()).decode()[-24:]

    def open_pull(
        self, head: str, files: dict[str, str], base: str = "main", lines: int = 1
    ) -> dict[str, Any]:
        self.files[head] = {**self.files[base], **files}
        number = len(self.pulls) + 1
        pull = {
            "number": number, "title": f"Fix from {head}", "state": "open", "merged": False,
            "base": {"ref": base}, "head": {"ref": head, "sha": self.sha(head)},
        }  # fmt: skip
        self.pulls.append(pull)
        self.changed[number] = [
            {"filename": name, "status": "changed", "additions": lines, "deletions": lines} for name in files
        ]
        return pull

    def get(self, path: str) -> Any:
        if path.startswith("repos/search"):
            return {"data": [{"id": 1, "full_name": REPO, "default_branch": "main", "archived": False,
                              "private": False, "description": ""}]}  # fmt: skip
        if path.startswith(f"repos/{REPO}/branches"):
            return [{"name": b, "commit": {"id": self.sha(b)}} for b in self.files]
        if m := re.fullmatch(rf"repos/{REPO}/pulls/(\d+)/files\?.*", path):
            return self.changed[int(m.group(1))]
        if path.startswith(f"repos/{REPO}/pulls"):
            return self.pulls
        if m := re.fullmatch(rf"repos/{REPO}/contents/(.+)\?ref=(.+)", path):
            name, ref = m.group(1), m.group(2).replace("%2F", "/")
            branch = {self.sha(b): b for b in self.files}.get(ref, ref)
            if name not in self.files.get(branch, {}):
                raise RestError(f"GET {path} -> HTTP 404: not found")
            return {"type": "file", "content": base64.b64encode(self.files[branch][name].encode()).decode()}
        raise AssertionError(path)


class FakeServices:
    def __init__(self, api: FakeGitea) -> None:
        self.api = api

    def rest(self, name: str) -> FakeGitea:
        assert name == "gitea"
        return self.api


@pytest.fixture
def git(tmp_path: Path) -> tuple[Any, FakeGitea]:
    api = FakeGitea()
    ctx = make_ctx(tmp_path)
    ctx.services = FakeServices(api)  # type: ignore[assignment]
    (ctx.run.baseline_dir / "gitea.json").write_text(json.dumps(state.snapshot(api)))
    return ctx, api


# --------------------------------------------------------------------------- the service


def test_gitea_service_definition() -> None:
    spec = services.load("gitea", env={})
    assert spec.project == "stick-gitea"
    assert spec.health.url == "http://127.0.0.1:8089/api/v1/repos/netops/lab-configs"
    auth = base64.b64encode(b"stick:stick-gitea-admin").decode()
    assert spec.api_settings is not None
    assert spec.health.headers == {"Authorization": f"Basic {auth}"} == spec.api_settings.headers
    assert isinstance(spec.snapshot, FilesSnapshot)
    assert not spec.snapshot.path.startswith(spec.snapshot.directory)  # the archive is not inside itself
    assert spec.init is not None and spec.init.steps[0].cmd[:4] == ["gitea", "admin", "user", "create"]
    assert spec.mcp is not None and len(spec.mcp.allow) == 12
    assert json.loads(spec.mcp.env["GITEA_EXTRA_HEADERS"]) == spec.health.headers
    other = services.load("gitea", lab.env({}, 1))
    assert other.mcp is not None and other.mcp.env["GITEA_HOST"] == "http://127.0.0.1:8189"


def test_files_snapshot_stops_the_service_around_the_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = services.load("gitea", env={})
    calls: list[list[str]] = []
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(lifecycle, "wait_healthy", lambda spec, timeout: None)
    lifecycle.take_snapshot(spec)
    stop, archive, start = calls
    assert stop[-2:] == ["stop", "gitea"] and "up" in start
    assert "run" in archive and "--no-deps" in archive  # a one-off container: the service is stopped
    assert archive[-4:] == ["-c", 'tar -czf "$1" -C "$0" .', "/var/lib/gitea", "/etc/gitea/baseline.tar.gz"]

    calls.clear()
    lifecycle.restore_snapshot(spec)
    probe, stop, unpack, start = calls
    assert probe[-3:] == ["test", "-f", "/etc/gitea/baseline.tar.gz"]
    assert stop[-2:] == ["stop", "gitea"] and "up" in start
    assert "-delete" in unpack[-3] and "tar -xzf" in unpack[-3]


def test_service_vars_give_the_basic_header() -> None:
    values = run.service_vars()["gitea"]
    assert values["url"] == "http://127.0.0.1:8089" and values["auth"].startswith("Basic ")


# --------------------------------------------------------------------------- the checks


def test_gitea_file_reads_a_file_at_a_ref(git: tuple[Any, FakeGitea]) -> None:
    ctx, api = git
    params = {"repo": REPO, "path": "intended/srl2.yaml"}
    assert check(ctx, "gitea_file", **params, contains=["old"], absent=["new"]).status == "pass"
    res = check(ctx, "gitea_file", **params, contains=["new"], absent=["old"])
    assert res.status == "fail" and res.observed == {"missing": ["new"], "present": ["old"]}
    assert check(ctx, "gitea_file", **params, ref="nosuch").hints == ["missing-object"]
    api.files["fix/x"] = {"intended/srl2.yaml": "description: new\n"}
    assert check(ctx, "gitea_file", **params, ref="fix/x", contains=["new"]).status == "pass"


def test_gitea_pull_wants_one_open_pull_request_with_exactly_the_files(git: tuple[Any, FakeGitea]) -> None:
    ctx, api = git
    params: dict[str, Any] = {
        "repo": REPO, "files": ["intended/srl2.yaml"], "max_lines": 2,
        "contains": {"intended/srl2.yaml": ["new"]}, "absent": {"intended/srl2.yaml": ["old"]},
    }  # fmt: skip
    assert check(ctx, "gitea_pull", **params).hints == ["missing-object"]  # none opened
    pull = api.open_pull("fix/srl2", {"intended/srl2.yaml": "description: new\n"})
    assert check(ctx, "gitea_pull", **params).status == "pass"

    api.files["fix/srl2"]["intended/srl2.yaml"] = "description: other\n"  # the right file, the wrong value
    pull["head"]["sha"] = api.sha("fix/srl2")
    res = check(ctx, "gitea_pull", **params)
    assert res.hints == ["wrong-config"] and res.observed == {"intended/srl2.yaml": {"missing": ["new"]}}
    api.files["fix/srl2"]["intended/srl2.yaml"] = "description: new\n"
    pull["head"]["sha"] = api.sha("fix/srl2")

    api.changed[1][0]["additions"] = 5  # the whole file rewritten
    assert "more than the change needs" in check(ctx, "gitea_pull", **params).message
    api.changed[1][0]["additions"] = 1
    api.changed[1].append({"filename": "README.md", "additions": 1, "deletions": 0})  # a second file
    assert check(ctx, "gitea_pull", **params).hints == ["collateral-change"]
    api.changed[1].pop()

    pull["merged"], pull["state"] = True, "closed"
    assert "is merged" in check(ctx, "gitea_pull", **params).message
    pull["merged"], pull["state"] = False, "open"
    api.open_pull("fix/again", {"intended/srl2.yaml": "description: new\n"})
    assert "2 new pull request(s)" in check(ctx, "gitea_pull", **params).message


def test_gitea_pull_ignores_pull_requests_from_before_the_attempt(git: tuple[Any, FakeGitea]) -> None:
    ctx, api = git
    api.open_pull("old/change", {"README.md": "x\n"})
    (ctx.run.baseline_dir / "gitea.json").write_text(json.dumps(state.snapshot(api)))
    assert check(ctx, "gitea_pull", repo=REPO).hints == ["missing-object"]
    api.open_pull("fix/srl2", {"intended/srl2.yaml": "description: new\n"})
    assert check(ctx, "gitea_pull", repo=REPO, files=["intended/srl2.yaml"]).status == "pass"


def test_gitea_unchanged_sees_commits_branches_and_pull_requests(git: tuple[Any, FakeGitea]) -> None:
    ctx, api = git
    assert check(ctx, "gitea_unchanged").status == "pass"
    api.open_pull("fix/srl2", {"intended/srl2.yaml": "description: new\n"})
    res = check(ctx, "gitea_unchanged")
    assert res.observed == [f"branches: added {REPO}:fix/srl2", f"pulls: added {REPO}:fix/srl2"]
    assert check(ctx, "gitea_unchanged", allow_new=["branches", "pulls"]).status == "pass"
    api.files["main"]["intended/srl2.yaml"] = "description: new\n"  # a commit straight to main
    res = check(ctx, "gitea_unchanged", allow_new=["branches", "pulls"])
    assert res.status == "fail" and res.observed == [f"branches: changed {REPO}:main (sha)"]
    (ctx.run.baseline_dir / "gitea.json").unlink()
    assert check(ctx, "gitea_unchanged").hints == ["env-error"]


def test_start_saves_a_gitea_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASK)
    api = FakeGitea()
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: None)
    monkeypatch.setattr(run, "run_script", lambda *a: None)
    monkeypatch.setattr(run, "rest_client", lambda name: api)
    info = run.start(task, tmp_path / "runs", FakeLab())  # type: ignore[arg-type]
    snap = json.loads((info.baseline_dir / "gitea.json").read_text())
    assert list(snap["branches"]) == [f"{REPO}:main"]
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, FakeLab())  # type: ignore[arg-type]
    assert env["STICK_GITEA_URL"] == "http://127.0.0.1:8089" and env["STICK_GITEA_AUTH"].startswith("Basic ")
