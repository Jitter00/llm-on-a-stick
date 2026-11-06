"""Deploy the base lab and check the routing works. Needs Docker, containerlab and the stick-frr image.

Run with: uv run pytest -m lab
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator

import pytest

from llm_on_a_stick.env import containerlab

pytestmark = pytest.mark.lab

PREFIX = "clab-stick-base-"


def dexec(node: str, *cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", PREFIX + node, *cmd], capture_output=True, text=True, check=False
    )


def wait_for(predicate, timeout: float = 240, interval: float = 5) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture(scope="module")
def lab() -> Iterator[None]:
    containerlab.deploy("base", reconfigure=True)
    try:
        yield
    finally:
        containerlab.destroy("base")


def frr_established_peers(node: str) -> int:
    res = dexec(node, "vtysh", "-c", "show bgp summary json")
    if res.returncode != 0:
        return 0
    peers = json.loads(res.stdout).get("ipv4Unicast", {}).get("peers", {})
    return sum(1 for p in peers.values() if p.get("state") == "Established")


@pytest.mark.parametrize("leaf", ["frr1", "frr2"])
def test_leaf_has_both_spine_sessions(lab: None, leaf: str) -> None:
    assert wait_for(lambda: frr_established_peers(leaf) == 2), f"{leaf}: BGP sessions to both spines not up"


def test_host_to_host_ping(lab: None) -> None:
    assert wait_for(lambda: dexec("h1", "ping", "-c", "2", "-W", "2", "10.1.2.10").returncode == 0)


def test_frr_cli_user_lands_in_vtysh(lab: None) -> None:
    res = dexec("frr1", "getent", "passwd", "admin")
    assert res.stdout.strip().endswith("/usr/bin/vtysh")


def test_frr_snmp_answers(lab: None) -> None:
    res = dexec("frr1", "snmpget", "-v2c", "-c", "stick-ro", "127.0.0.1", "SNMPv2-MIB::sysName.0")
    assert "frr1" in res.stdout
