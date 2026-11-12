"""Loki against the live base lab: syslog from both router OSes arrives with the router's name as a label,
SR Linux's login and commit events are there, reset empties the store, and Grafana's MCP server reads it.

Run with: uv run pytest -m lab tests/integration/test_loki.py
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator

import pytest
from labutil import check_mcp_server, dexec, service_session, wait_for

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle

pytestmark = pytest.mark.lab

ROUTERS = ["srl1", "srl2", "frr1", "frr2"]


@pytest.fixture(scope="module")
def loki(lab: None) -> Iterator[str]:
    with service_session("loki") as spec:
        lifecycle.restore_snapshot(spec)  # start empty, whatever an earlier run left behind
        api = spec.api_settings
        assert api is not None
        yield api.base_url.rstrip("/")
        lifecycle.restore_snapshot(spec)


def lines(base: str, logql: str) -> list[tuple[dict[str, str], str]]:
    """(labels, line) of what matches in the last 15 minutes."""
    query = urllib.parse.urlencode({"query": logql, "since": "15m", "limit": "1000"})
    with urllib.request.urlopen(f"{base}/loki/api/v1/query_range?{query}", timeout=10) as resp:  # noqa: S310
        streams = json.load(resp)["data"]["result"]
    return [(s["stream"], value[1]) for s in streams for value in s["values"]]


def log_on(node: str, text: str) -> None:
    """Write one line to the router's own syslog."""
    if node.startswith("srl"):  # SR Linux forwards local6 (its own applications), auth and authpriv
        res = dexec(node, "logger", "-p", "local6.notice", "-t", "stick-test", text)
    else:
        res = dexec(node, "logger", "-t", "stick-test", text)
    assert res.returncode == 0, res.stderr


def test_a_line_from_each_router_arrives_with_its_name(loki: str) -> None:
    marker = f"stick-marker-{uuid.uuid4().hex[:8]}"
    for node in ROUTERS:
        log_on(node, f"{marker} from {node}")
    assert wait_for(lambda: len(lines(loki, f'{{job="syslog"}} |= "{marker}"')) == 4, timeout=60, interval=1)
    got = {labels["host"]: line for labels, line in lines(loki, f'{{job="syslog"}} |= "{marker}"')}
    assert {host: line.strip() for host, line in got.items()} == {n: f"{marker} from {n}" for n in ROUTERS}
    labels = lines(loki, f'{{host="frr1"}} |= "{marker}"')[0][0]
    assert labels["app"] == "stick-test" and labels["severity"] == "notice" and labels["facility"] == "user"


def test_sr_linux_logs_who_committed_what(loki: str) -> None:
    desc = f"stick-{uuid.uuid4().hex[:8]}"
    res = dexec("srl1", "sr_cli", "-ec", f"set / interface ethernet-1/1 description {desc}")
    assert res.returncode == 0, res.stdout + res.stderr
    try:
        assert wait_for(lambda: bool(lines(loki, f'{{host="srl1", app="sr_cli"}} |= "{desc}"')), 60, 1)
        assert wait_for(lambda: bool(lines(loki, '{host="srl1"} |= "commitSucceeded"')), 60, 1)
        assert "by user" in lines(loki, '{host="srl1"} |= "commitSucceeded"')[0][1]
    finally:
        dexec("srl1", "sr_cli", "-ec", "delete / interface ethernet-1/1 description")


def test_frr_logs_a_bgp_session_reset(loki: str) -> None:
    res = dexec("frr1", "vtysh", "-c", "clear bgp 10.0.1.0")
    assert res.returncode == 0, res.stderr
    query = '{host="frr1", app="bgpd"} |= "ADJCHANGE: neighbor 10.0.1.0" |= "Down User reset"'
    assert wait_for(lambda: bool(lines(loki, query)), timeout=60, interval=1)
    assert wait_for(
        lambda: bool(lines(loki, '{host="srl1"} |= "Peer 10.0.1.1 moved"')), timeout=60, interval=1
    )


def test_reset_empties_the_store(loki: str) -> None:
    marker = f"stick-marker-{uuid.uuid4().hex[:8]}"
    log_on("frr2", marker)
    assert wait_for(lambda: bool(lines(loki, f'{{job="syslog"}} |= "{marker}"')), timeout=60, interval=1)
    lifecycle.restore_snapshot(services.load("loki"))
    assert lines(loki, f'{{job="syslog"}} |= "{marker}"') == []
    log_on("frr2", f"{marker} again")  # and it takes lines again
    assert wait_for(lambda: len(lines(loki, f'{{job="syslog"}} |= "{marker}"')) == 1, timeout=60, interval=1)


def test_its_mcp_server_starts_and_answers(loki: str) -> None:
    check_mcp_server("loki", "list_datasources", {}, '"uid":"loki"')
