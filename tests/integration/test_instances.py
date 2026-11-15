"""Two lab instances side by side (`stick --instance N`): each has its own routers, names and subnet, and
what happens on one leaves the other alone.

Deploys a second base lab (about 4 GB of RAM, two minutes) next to the session's. STICK_SKIP_INSTANCES=1
skips it on a machine that is too small for two.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from labutil import wait_for

from llm_on_a_stick import lab as instances
from llm_on_a_stick.env import containerlab
from llm_on_a_stick.grading.labstate import DockerLabState

pytestmark = pytest.mark.lab

MARK = "stick-instances-test"


def _established(state: DockerLabState, node: str) -> int:
    return sum(1 for s in state.bgp_sessions(node).values() if s == "established")


@pytest.fixture
def other(lab: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """The next instance's base lab, deployed for this test unless it was running; STICK_INSTANCE points
    at it only while the fixture deploys and removes it."""
    if os.environ.get("STICK_SKIP_INSTANCES"):
        pytest.skip("STICK_SKIP_INSTANCES is set")
    here = instances.instance()
    n = (here + 1) % instances.MAX_INSTANCES
    try:
        held = instances.lock(n)
        held.__enter__()
    except instances.InstanceError:
        pytest.skip(f"lab instance {n} is in use")
    monkeypatch.setenv(instances.INSTANCE_VAR, str(n))
    was_running = any(node.state == "running" for node in containerlab.inspect("base"))
    containerlab.deploy("base")
    monkeypatch.setenv(instances.INSTANCE_VAR, str(here))
    try:
        yield n
    finally:
        monkeypatch.setenv(instances.INSTANCE_VAR, str(n))
        if not was_running:
            containerlab.destroy("base")
        monkeypatch.setenv(instances.INSTANCE_VAR, str(here))
        held.__exit__(None, None, None)


def _state(n: int, monkeypatch: pytest.MonkeyPatch) -> DockerLabState:
    """The lab state reader of instance n (it reads the instance when it is created)."""
    here = instances.instance()
    monkeypatch.setenv(instances.INSTANCE_VAR, str(n))
    try:
        return DockerLabState("base")
    finally:
        monkeypatch.setenv(instances.INSTANCE_VAR, str(here))


def test_two_instances_run_side_by_side(other: int, monkeypatch: pytest.MonkeyPatch) -> None:
    here = instances.instance()
    mine, theirs = DockerLabState("base"), _state(other, monkeypatch)

    # Different containers, different subnets, the same host numbers.
    assert mine.nodes()["frr1"].container == f"clab-{instances.name(here)}-base-frr1"
    assert theirs.nodes()["frr1"].container == f"clab-{instances.name(other)}-base-frr1"
    for name, node in mine.nodes().items():
        twin = theirs.nodes()[name]
        assert node.mgmt_ipv4.startswith(instances.mgmt_prefix(here) + ".")
        assert twin.mgmt_ipv4.startswith(instances.mgmt_prefix(other) + ".")
        assert node.mgmt_ipv4.rsplit(".", 1)[1] == twin.mgmt_ipv4.rsplit(".", 1)[1]

    # The second lab converges like the first, and logs to the syslog receiver of its own subnet.
    assert wait_for(lambda: all(_established(theirs, n) == 2 for n in ("frr1", "frr2")))
    assert all(_established(mine, n) == 2 for n in ("frr1", "frr2"))
    assert f"remote-server {instances.service_ip('loki', other)} " in theirs.running_config("srl1")
    assert f"remote-server {instances.service_ip('loki', here)} " in mine.running_config("srl1")

    # A change on one is not on the other, and restoring one leaves the other's change in place.
    container = theirs.nodes()["frr1"].container
    theirs._exec(
        theirs.nodes()["frr1"], "vtysh", "-c", "configure terminal", "-c", "interface eth3",
        "-c", f"description {MARK}",
    )  # fmt: skip
    try:
        assert MARK in theirs.running_config("frr1"), container
        assert MARK not in mine.running_config("frr1")
        mine.restore_config("frr1")
        assert MARK in theirs.running_config("frr1")
    finally:
        theirs.restore_config("frr1")
    assert MARK not in theirs.running_config("frr1")
