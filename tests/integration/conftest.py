"""Session-wide lab fixture: deploy the base lab once for every integration test that needs it."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from labutil import frr_established_peers, wait_for

from llm_on_a_stick.env import containerlab


def _base_lab_running() -> bool:
    try:
        return any(n.state == "running" for n in containerlab.inspect("base"))
    except Exception:  # not deployed (or containerlab can't tell): treat as not running
        return False


@pytest.fixture(scope="session")
def lab() -> Iterator[None]:
    """The base lab, deployed fresh and converged (both leaves have both spine sessions).

    A lab that was already running before the tests (you were using it) is left running afterwards;
    one the tests deployed themselves is destroyed again."""
    was_running = _base_lab_running()
    containerlab.deploy("base", reconfigure=True)
    try:
        converged = wait_for(lambda: all(frr_established_peers(n) == 2 for n in ("frr1", "frr2")))
        assert converged, "base lab BGP did not converge"
        yield
    finally:
        if not was_running:
            containerlab.destroy("base")
