"""Gitea for grading: files at a ref, pull requests, a snapshot of what a task may touch, and what changed
since.

`stick task start` saves the snapshot to baseline/gitea.json right after setup; the `gitea_unchanged` check
compares it with the service at grading time. A branch is its name and the commit it points at, so a commit
pushed to a branch shows as that branch changed.
"""

from __future__ import annotations

import base64
from typing import Any, Protocol
from urllib.parse import quote

from llm_on_a_stick.grading.librenmsstate import diff as diff  # the same rules: kind / kind:label allow lists
from llm_on_a_stick.services.seed import RestError

SERVICE = "gitea"
PAGE = 50  # Gitea's largest page; the lab's repositories stay far below it

REPO_FIELDS = ("default_branch", "archived", "private", "description")
PULL_FIELDS = ("title", "state", "merged", "base", "head_sha")

Snapshot = dict[str, dict[str, dict[str, Any]]]  # kind (repos, branches, pulls) -> key -> object


class Api(Protocol):
    def get(self, path: str) -> Any: ...


def _missing(exc: RestError) -> bool:
    return "HTTP 404" in str(exc)


def repos(api: Api) -> list[dict[str, Any]]:
    return list((api.get(f"repos/search?limit={PAGE}") or {}).get("data") or [])


def branches(api: Api, repo: str) -> dict[str, str]:
    """Branch name -> the commit it points at."""
    found = api.get(f"repos/{repo}/branches?limit={PAGE}") or []
    return {b["name"]: b["commit"]["id"] for b in found}


def pulls(api: Api, repo: str) -> list[dict[str, Any]]:
    """Every pull request of the repository, open or not, in the fields the checks use."""
    out = []
    for p in api.get(f"repos/{repo}/pulls?state=all&limit={PAGE}") or []:
        out.append(
            {
                "number": p["number"],
                "title": p.get("title", ""),
                "state": p.get("state", ""),
                "merged": bool(p.get("merged")),
                "base": (p.get("base") or {}).get("ref", ""),
                "head": (p.get("head") or {}).get("ref", ""),
                "head_sha": (p.get("head") or {}).get("sha", ""),
            }
        )
    return out


def pull_files(api: Api, repo: str, number: int) -> list[dict[str, Any]]:
    """The files a pull request changes: `filename`, `status`, `additions`, `deletions`."""
    return list(api.get(f"repos/{repo}/pulls/{number}/files?limit={PAGE}") or [])


def file_text(api: Api, repo: str, path: str, ref: str) -> str | None:
    """The file's text at a branch, tag or commit; None when the file or the ref isn't there."""
    try:
        found = api.get(f"repos/{repo}/contents/{quote(path)}?ref={quote(ref, safe='')}")
    except RestError as exc:
        if _missing(exc):
            return None
        raise
    if not isinstance(found, dict) or found.get("type") != "file":
        return None
    return base64.b64decode(found.get("content") or "").decode("utf-8", "replace")


def snapshot(api: Api) -> Snapshot:
    snap: Snapshot = {"repos": {}, "branches": {}, "pulls": {}}
    for repo in repos(api):
        name = repo["full_name"]
        snap["repos"][str(repo["id"])] = {"label": name, **{k: repo.get(k) for k in REPO_FIELDS}}
        for branch, sha in branches(api, name).items():
            snap["branches"][f"{name}:{branch}"] = {"label": f"{name}:{branch}", "sha": sha}
        for pull in pulls(api, name):
            snap["pulls"][f"{name}#{pull['number']}"] = {
                "label": f"{name}:{pull['head']}",  # by its head branch: a new one's number isn't known
                **{k: pull[k] for k in PULL_FIELDS},
            }
    return snap
