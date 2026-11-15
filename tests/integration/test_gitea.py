"""The Gitea service by itself (no lab): first boot leaves the seeded repository, a reset takes commits,
branches and pull requests away again, and Gitea's MCP server reads the repository.

Run with: uv run pytest -m lab tests/integration/test_gitea.py
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from labutil import check_mcp_server, service_session

from llm_on_a_stick import services
from llm_on_a_stick.grading import giteastate as state
from llm_on_a_stick.grading.run import rest_client
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.seed import RestClient

pytestmark = pytest.mark.lab

REPO = "netops/lab-configs"


@pytest.fixture(scope="module")
def gitea() -> Iterator[RestClient]:
    with service_session("gitea") as spec:
        lifecycle.restore_snapshot(spec)  # start from the baseline, whatever an earlier run left behind
        yield rest_client("gitea")
        lifecycle.restore_snapshot(spec)


def test_first_boot_leaves_the_seeded_repository(gitea: RestClient) -> None:
    assert [r["full_name"] for r in state.repos(gitea)] == [REPO]
    assert list(state.branches(gitea, REPO)) == ["main"]
    assert state.pulls(gitea, REPO) == []
    assert "lab-configs" in (state.file_text(gitea, REPO, "README.md", "main") or "")
    assert state.file_text(gitea, REPO, "nosuch.txt", "main") is None
    assert state.file_text(gitea, REPO, "README.md", "nosuch") is None


def test_reset_takes_commits_branches_and_pull_requests_away(gitea: RestClient) -> None:
    before = state.snapshot(gitea)
    gitea.post(f"repos/{REPO}/branches", {"new_branch_name": "fix/x", "old_branch_name": "main"})
    gitea.post(
        f"repos/{REPO}/contents/intended/srl2.yaml",
        {"content": "ZGVzY3JpcHRpb246IG5ldwo=", "branch": "fix/x", "message": "record it"},
    )
    pull = gitea.post(f"repos/{REPO}/pulls", {"head": "fix/x", "base": "main", "title": "Record it"})
    assert state.file_text(gitea, REPO, "intended/srl2.yaml", "fix/x") == "description: new\n"
    assert state.file_text(gitea, REPO, "intended/srl2.yaml", "main") is None
    assert [f["filename"] for f in state.pull_files(gitea, REPO, pull["number"])] == ["intended/srl2.yaml"]
    problems = state.diff(before, state.snapshot(gitea), [], [], [])
    assert problems == [f"branches: added {REPO}:fix/x", f"pulls: added {REPO}:fix/x"]

    lifecycle.restore_snapshot(services.load("gitea"))
    assert state.snapshot(gitea) == before  # the same commit on main too: the repositories went back as well


def test_mcp_server_reads_the_repository(gitea: RestClient) -> None:
    check_mcp_server(
        "gitea",
        "get_file_contents",
        {"owner": "netops", "repo": "lab-configs", "path": "README.md"},
        "README.md",
    )
