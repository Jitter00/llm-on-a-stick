"""The telemetry service against the live base lab: both SR Linux routers stream to gNMIc, Prometheus has
their states as numbers, a port going down shows within two scrapes, reset empties the store, and Grafana's
MCP server reads it through the Grafana of the `loki` service.

Run with: uv run pytest -m lab tests/integration/test_telemetry.py
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Iterator

import pytest
from labutil import check_mcp_server, dexec, service_session, wait_for

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle

pytestmark = pytest.mark.lab


@pytest.fixture(scope="module")
def prometheus(lab: None) -> Iterator[str]:
    with service_session("loki"), service_session("telemetry") as spec:  # Grafana is in `loki`
        lifecycle.restore_snapshot(spec)  # start empty, whatever an earlier run left behind
        api = spec.api_settings
        assert api is not None
        yield api.base_url.rstrip("/")
        lifecycle.restore_snapshot(spec)


def query(base: str, promql: str) -> list[tuple[dict[str, str], float]]:
    """(labels, value) of every series an instant query returns."""
    url = f"{base}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        result = json.load(resp)["data"]["result"]
    return [(r["metric"], float(r["value"][1])) for r in result]


def value(base: str, promql: str) -> float | None:
    got = query(base, promql)
    return got[0][1] if got else None


def srl_set(node: str, command: str) -> None:
    res = dexec(node, "sr_cli", "-ec", command)
    assert res.returncode == 0, res.stderr


def test_both_routers_stream_states_as_numbers(prometheus: str) -> None:
    assert wait_for(lambda: value(prometheus, "count(session_state == 1)") == 4, timeout=60, interval=1)
    sessions = {(m["source"], m["neighbor_peer_address"]) for m, _ in query(prometheus, "session_state")}
    assert sessions == {
        ("srl1", "10.0.1.1"), ("srl1", "10.0.1.3"), ("srl2", "10.0.2.1"), ("srl2", "10.0.2.3"),
    }  # fmt: skip
    both = query(prometheus, "admin_state == 1 and oper_state == 1")
    up = {(m["source"], m["interface_name"]) for m, _ in both}
    assert up == {(r, p) for r in ("srl1", "srl2") for p in ("ethernet-1/1", "ethernet-1/2")}
    labels, _ = query(prometheus, 'in_octets{source="srl1", interface_name="ethernet-1/1"}')[0]
    assert "subscription_name" not in labels


def test_a_state_that_does_not_change_stays(prometheus: str) -> None:
    """gNMIc drops a value it hasn't heard for a minute unless told not to; a state is sent once."""
    assert wait_for(lambda: value(prometheus, "count(oper_state)") is not None, timeout=60, interval=1)
    before = value(prometheus, "count(oper_state)")
    assert not wait_for(lambda: value(prometheus, "count(oper_state)") != before, timeout=75, interval=5)


def test_a_port_going_down_shows_with_its_session(prometheus: str) -> None:
    port = 'oper_state{source="srl1", interface_name="ethernet-1/1"}'
    session = 'session_state{source="srl1", neighbor_peer_address="10.0.1.1"}'
    assert wait_for(lambda: value(prometheus, session) == 1, timeout=60, interval=1)
    srl_set("srl1", "set / interface ethernet-1/1 admin-state disable")
    try:
        assert wait_for(lambda: value(prometheus, port) == 0, timeout=20, interval=1)
        assert wait_for(lambda: value(prometheus, session) == 0, timeout=20, interval=1)
        assert value(prometheus, 'admin_state{source="srl1", interface_name="ethernet-1/1"}') == 0
    finally:
        srl_set("srl1", "set / interface ethernet-1/1 admin-state enable")
    assert wait_for(lambda: value(prometheus, session) == 1, timeout=90, interval=1)
    assert value(prometheus, f"resets({port}[5m])") == 1


def test_reset_empties_the_store_and_the_present_comes_back(prometheus: str) -> None:
    assert wait_for(lambda: value(prometheus, "count(session_state)") == 4, timeout=60, interval=1)
    assert wait_for(lambda: (value(prometheus, "count_over_time(up[5m])") or 0) >= 3, timeout=60, interval=1)
    lifecycle.restore_snapshot(services.load("telemetry"))
    assert (value(prometheus, "count_over_time(up[5m])") or 0) <= 1  # the history is gone
    assert wait_for(lambda: value(prometheus, "count(session_state == 1)") == 4, timeout=30, interval=1)


def test_its_mcp_server_starts_and_answers(prometheus: str) -> None:
    check_mcp_server("telemetry", "list_datasources", {"type": "prometheus"}, '"uid":"prometheus"')
