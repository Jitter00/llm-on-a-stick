"""The Batfish service against the live base lab: the setup helpers dump frr1 and frr2 (and the EOS
stand-ins for srl1 and srl2) into a snapshot that Batfish reads without a parse issue, with the fabric's four
sessions up on both sides; a change on a router shows in the next snapshot; reset empties Batfish; and its
MCP server reads it.

Run with: uv run pytest -m lab tests/integration/test_batfish.py
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from labutil import PREFIX, check_mcp_server, dexec, service_session

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle

pytestmark = pytest.mark.lab

LIB = Path(__file__).parent.parent.parent / "sections" / "_lib"


@pytest.fixture(scope="module")
def batfish(lab: None) -> Iterator[str]:
    with service_session("batfish") as spec:
        lifecycle.restore_snapshot(spec)  # start empty, whatever an earlier run left behind
        yield spec.health.url.removesuffix("/v2/networks")
        lifecycle.restore_snapshot(spec)


def bash(url: str, script: str) -> str:
    """Run a script with the setup scripts' helpers and environment; its output."""
    env = os.environ | {
        "STICK_LIB": str(LIB),
        "STICK_BATFISH_URL": url,
        "STICK_NODE_FRR1": f"{PREFIX}frr1",
        "STICK_NODE_FRR2": f"{PREFIX}frr2",
    }
    done = subprocess.run(
        ["/bin/bash", "-c", f'set -euo pipefail; source "$STICK_LIB/common.sh"; {script}'],
        env=env, capture_output=True, text=True, timeout=180, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout


def query(url: str, snapshot: str, python: str) -> object:
    """A pybatfish expression on a snapshot, as JSON."""
    code = f"import json\nbf.set_snapshot('{snapshot}')\nprint(json.dumps({python}))"
    return json.loads(bash(url, f"bf_py <<'PY'\n{code}\nPY"))


def rows(url: str, snapshot: str, question: str, columns: list[str]) -> object:
    """These columns of a question's answer (e.g. "bgpSessionStatus()"), as sorted lists of strings."""
    frame = f"bf.q.{question}.answer().frame()[{columns!r}]"
    return query(url, snapshot, f"sorted(map(list, {frame}.astype(str).values))")


def test_a_snapshot_of_the_lab_parses_cleanly_with_the_fabric_up(batfish: str) -> None:
    bash(batfish, "bf_snapshot current")
    assert query(batfish, "current", "len(bf.q.initIssues().answer().frame())") == 0
    statuses = query(batfish, "current", "sorted(set(bf.q.fileParseStatus().answer().frame().Status))")
    assert statuses == ["PASSED"]
    sessions = rows(batfish, "current", "bgpSessionStatus()", ["Node", "Remote_IP", "Established_Status"])
    assert sessions == [
        ["frr1", "10.0.1.0", "ESTABLISHED"], ["frr1", "10.0.2.0", "ESTABLISHED"],
        ["frr2", "10.0.1.2", "ESTABLISHED"], ["frr2", "10.0.2.2", "ESTABLISHED"],
        ["srl1", "10.0.1.1", "ESTABLISHED"], ["srl1", "10.0.1.3", "ESTABLISHED"],
        ["srl2", "10.0.2.1", "ESTABLISHED"], ["srl2", "10.0.2.3", "ESTABLISHED"],
    ]  # fmt: skip
    routes = "sorted(bf.q.routes(nodes='frr1', network='10.1.2.0/24').answer().frame().Next_Hop.astype(str))"
    assert query(batfish, "current", routes) == ["ip 10.0.1.0", "ip 10.0.2.0"]


def test_a_change_on_a_router_shows_in_the_next_snapshot(batfish: str) -> None:
    asn = ["vtysh", "-c", "conf t", "-c", "router bgp 65102", "-c"]
    assert dexec("frr2", *asn, "neighbor 10.0.2.2 remote-as 64999").returncode == 0
    try:
        bash(batfish, "bf_snapshot changed")
    finally:
        assert dexec("frr2", *asn, "neighbor 10.0.2.2 remote-as 65002").returncode == 0
    bf_compat = "bf.q.bgpSessionCompatibility(nodes='frr2').answer().frame()"
    rows = query(
        batfish,
        "changed",
        f"sorted(map(list, {bf_compat}[['Remote_IP', 'Configured_Status']].astype(str).values))",
    )
    assert rows == [["10.0.1.2", "UNIQUE_MATCH"], ["10.0.2.2", "HALF_OPEN"]]


def test_reset_empties_batfish(batfish: str) -> None:
    bash(batfish, "bf_snapshot current")
    lifecycle.restore_snapshot(services.load("batfish"))
    assert (
        json.loads(bash(batfish, "bf_py <<< 'import json; print(json.dumps(bf.list_snapshots()))'")) == []
    )  # (bf_py makes the network)


def test_its_mcp_server_starts_and_answers(batfish: str) -> None:
    bash(batfish, "bf_snapshot current")
    arguments = {"network": "lab", "snapshot": "current", "nodes": "frr1"}
    check_mcp_server("batfish", "get_bgp_session_status", arguments, "ESTABLISHED")
