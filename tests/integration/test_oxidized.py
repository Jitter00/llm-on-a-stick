"""Oxidized against the live base lab: backups, content per OS, on-demand re-backup, reset.

Run with: uv run pytest -m lab tests/integration/test_oxidized.py
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from labutil import dexec, wait_for

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle

pytestmark = pytest.mark.lab

NODES = ("srl1", "srl2", "frr1", "frr2")


def api(path: str) -> Any:
    spec = services.load("oxidized")
    base = spec.health.url.rsplit("/", 1)[0]
    with urllib.request.urlopen(f"{base}/{path}", timeout=10) as resp:  # noqa: S310 (local test URL)
        body = resp.read().decode("utf-8")
    return json.loads(body) if path.endswith(".json") or "json" in path else body


def statuses() -> dict[str, str]:
    return {n["name"]: (n.get("last") or {}).get("status", "pending") for n in api("nodes.json")}


def versions(node: str) -> int:
    return len(api(f"node/version.json?node_full={node}"))


def all_backed_up() -> bool:
    return all(s == "success" for s in statuses().values()) and len(statuses()) == len(NODES)


@pytest.fixture(scope="module")
def oxidized(lab: None) -> Iterator[None]:
    spec = services.load("oxidized")
    lifecycle.up(spec)
    lifecycle.restore_snapshot(spec)  # start from an empty repo, whatever ran before
    assert wait_for(all_backed_up, timeout=120, interval=3), f"not all nodes backed up: {statuses()}"
    yield


def test_every_device_backed_up(oxidized: None) -> None:
    assert statuses() == dict.fromkeys(NODES, "success")


def test_srlinux_backup_content(oxidized: None) -> None:
    cfg = api("node/fetch/srl1")
    assert "set / network-instance default protocols bgp autonomous-system 65001" in cfg
    assert "admin-state enable" in cfg


def test_frr_backup_content_is_clean(oxidized: None) -> None:
    cfg = api("node/fetch/frr2")
    assert "router bgp 65102" in cfg
    assert not cfg.startswith("Building configuration")
    assert "Can't open" not in cfg  # vtysh warnings must not leak into backups


def test_backup_matches_device(oxidized: None) -> None:
    """What Oxidized stored is what the device reports right now (the basis of consistency tasks)."""
    live = dexec("frr1", "vtysh", "-c", "show running-config").stdout
    stored = api("node/fetch/frr1")
    live_lines = [line for line in live.splitlines() if line and not line.startswith(("Building", "Current"))]
    assert stored.split() == "\n".join(live_lines).split()


def test_change_then_backup_now_creates_a_version(oxidized: None) -> None:
    before = versions("frr1")
    res = dexec(
        "frr1", "vtysh", "-c", "conf t", "-c", "interface eth3", "-c", "description stick-test-change"
    )
    assert res.returncode == 0
    api("node/next/frr1")
    assert wait_for(lambda: versions("frr1") == before + 1, timeout=60, interval=2)
    assert "description stick-test-change" in api("node/fetch/frr1")


def test_reset_empties_the_repo_and_refetches(oxidized: None) -> None:
    assert versions("frr1") >= 2  # from the previous test
    lifecycle.restore_snapshot(services.load("oxidized"))
    assert wait_for(all_backed_up, timeout=120, interval=3)
    assert versions("frr1") == 1
