"""Helpers shared by the integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.spec import ServiceSpec

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


@contextmanager
def service_session(name: str) -> Iterator[ServiceSpec]:
    """Start a service for the tests and leave the machine as we found it.

    If the service wasn't running before, it's stopped again afterwards (volumes are kept, so the
    next start is fast). Set STICK_KEEP_SERVICES=1 to leave it running anyway.
    """
    spec = services.load(name)
    was_running = any(row["state"] == "running" for row in lifecycle.status(spec))
    lifecycle.up(spec)
    try:
        yield spec
    finally:
        if not was_running and not os.environ.get("STICK_KEEP_SERVICES"):
            lifecycle.down(spec)
