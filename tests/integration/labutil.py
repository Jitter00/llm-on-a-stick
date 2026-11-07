"""Helpers shared by the integration tests."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable

PREFIX = "clab-stick-base-"


def dexec(node: str, *cmd: str) -> subprocess.CompletedProcess[str]:
    """Run a command inside a lab node's container."""
    return subprocess.run(
        ["docker", "exec", PREFIX + node, *cmd], capture_output=True, text=True, check=False
    )


def wait_for(predicate: Callable[[], bool], timeout: float = 240, interval: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def frr_established_peers(node: str) -> int:
    res = dexec(node, "vtysh", "-c", "show bgp summary json")
    if res.returncode != 0:
        return 0
    peers = json.loads(res.stdout).get("ipv4Unicast", {}).get("peers", {})
    return sum(1 for p in peers.values() if p.get("state") == "Established")
