"""The SuzieQ service against the live base lab: the poller reads frr1 and frr2 over SSH, including the tables
that need the adapted commands (BGP, device, LLDP), a BGP session going down shows with its reason and its
history, reset empties the store, and the MCP server made from SuzieQ's API description reads it.

Run with: uv run pytest -m lab tests/integration/test_suzieq.py
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from labutil import check_mcp_server, dexec, frr_established_peers, service_session, wait_for

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle

pytestmark = pytest.mark.lab

Rows = list[dict[str, Any]]


@pytest.fixture(scope="module")
def suzieq(lab: None) -> Iterator[str]:
    with service_session("suzieq") as spec:
        lifecycle.restore_snapshot(spec)  # start empty, whatever an earlier run left behind
        api = spec.api_settings
        assert api is not None
        yield api.base_url.rstrip("/")
        lifecycle.restore_snapshot(spec)


def get(base: str, table: str, verb: str = "show", **filters: str) -> Rows:
    url = f"{base}/{table}/{verb}?{urllib.parse.urlencode(filters)}"
    req = urllib.request.Request(url, headers={"access_token": "stick-suzieq-key"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        rows: Rows = json.load(resp)
    return rows


def established(base: str) -> int:
    return sum(r["state"] == "Established" for r in get(base, "bgp"))


def test_it_needs_the_api_key(suzieq: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(f"{suzieq}/device/show", timeout=10)  # noqa: S310
    assert err.value.code == 401


def test_both_frr_routers_are_polled_with_every_table_the_tasks_use(suzieq: str) -> None:
    assert wait_for(lambda: established(suzieq) == 4, timeout=90, interval=2)
    devices = {r["hostname"]: r for r in get(suzieq, "device")}
    assert set(devices) == {"frr1", "frr2"}
    assert all(d["status"] == "alive" and d["vendor"] == "Alpine" for d in devices.values())
    sessions = {(r["hostname"], r["peer"], r["peerAsn"]) for r in get(suzieq, "bgp")}
    assert sessions == {
        ("frr1", "10.0.1.0", 65001), ("frr1", "10.0.2.0", 65002),
        ("frr2", "10.0.1.2", 65001), ("frr2", "10.0.2.2", 65002),
    }  # fmt: skip
    neighbours = {(r["hostname"], r["ifname"], r["peerHostname"]) for r in get(suzieq, "lldp")}
    assert {("frr1", "eth1", "srl1"), ("frr1", "eth2", "srl2"), ("frr2", "eth2", "srl2")} <= neighbours
    # Routes learnt over BGP arrive a poll after the sessions came up.
    assert wait_for(
        lambda: get(suzieq, "route", hostname="frr1", prefix="10.1.2.0/24"), timeout=60, interval=2
    )
    routes = get(suzieq, "route", hostname="frr1", prefix="10.1.2.0/24")
    assert sorted(routes[0]["nexthopIps"]) == ["10.0.1.0", "10.0.2.0"]
    addresses = {
        (r["hostname"], r["ifname"]) for r in get(suzieq, "address") if "10.1.1.1/24" in r["ipAddressList"]
    }
    assert addresses == {("frr1", "eth3")}


def test_a_session_going_down_shows_with_its_reason_and_history(suzieq: str) -> None:
    assert wait_for(lambda: established(suzieq) == 4, timeout=90, interval=2)
    shut = ["vtysh", "-c", "conf t", "-c", "router bgp 65101", "-c"]
    assert dexec("frr1", *shut, "neighbor 10.0.2.0 shutdown").returncode == 0
    try:
        assert wait_for(lambda: established(suzieq) == 3, timeout=60, interval=1)
        failed = get(suzieq, "bgp", "assert", result="fail")
        assert [(r["hostname"], r["peer"], r["assertReason"]) for r in failed] == [
            ("frr1", "10.0.2.0", "Admin. shutdown:")
        ]
    finally:
        assert dexec("frr1", *shut, "no neighbor 10.0.2.0 shutdown").returncode == 0
    assert wait_for(lambda: frr_established_peers("frr1") == 2, timeout=90, interval=2)
    assert wait_for(lambda: established(suzieq) == 4, timeout=60, interval=1)
    states = [r["state"] for r in get(suzieq, "bgp", hostname="frr1", peer="10.0.2.0", view="all")]
    assert "NotEstd" in states  # the history keeps it


def test_reset_empties_the_store_and_the_present_comes_back(suzieq: str) -> None:
    assert wait_for(lambda: established(suzieq) == 4, timeout=90, interval=2)
    lifecycle.restore_snapshot(services.load("suzieq"))
    assert wait_for(lambda: established(suzieq) == 4, timeout=60, interval=1)
    rows = get(suzieq, "bgp", hostname="frr1", peer="10.0.2.0", view="all")
    assert [r["state"] for r in rows] == ["Established"]  # nothing from before the reset


def test_its_mcp_server_starts_and_answers(suzieq: str) -> None:
    assert wait_for(lambda: established(suzieq) == 4, timeout=90, interval=2)
    check_mcp_server("suzieq", "query_bgp_api_v2_bgp", {"verb": "assert"}, '"result":"pass"')
