"""Helpers shared by the integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_on_a_stick import services
from llm_on_a_stick.runner import mcp
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


MCP_SNAPSHOTS = Path(__file__).parent.parent / "fixtures" / "mcp_tools"


def check_mcp_server(name: str, tool: str, arguments: dict[str, Any], expect: str) -> None:
    """The service's MCP server (the `mcp:` block of its service.yaml) starts from the stick-mcp image,
    offers exactly the tools of tests/fixtures/mcp_tools/<name>.json (names, descriptions and schemas, as the
    model is shown them), and answers one read call with `expect` in its text.

    A different tool list means the pinned server changed: look at what changed, then refresh the snapshot
    with STICK_UPDATE_MCP_SNAPSHOTS=1 (the unit tests check its size)."""
    server = services.load(name).mcp
    assert server is not None, f"{name} has no mcp: block"
    mcp.ensure_image()
    snapshot = MCP_SNAPSHOTS / f"{name}.json"
    with (
        tempfile.TemporaryDirectory() as logs,
        mcp.McpHub({name: server}, f"test-{os.getpid()}", Path(logs)) as hub,
    ):
        shown = [asdict(d) for d in hub.defs]
        if os.environ.get("STICK_UPDATE_MCP_SNAPSHOTS"):
            snapshot.write_text(json.dumps(shown, indent=1) + "\n", encoding="utf-8")
        assert shown == json.loads(snapshot.read_text(encoding="utf-8")), f"{name}: tool list changed"
        res = hub.call(mcp.tool_name(name, tool), arguments)
        assert not res.is_error and expect in res.output, res.output
