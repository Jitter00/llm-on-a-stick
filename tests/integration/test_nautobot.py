"""Nautobot service: up -> seeded -> agent-style change -> reset restores the baseline.

Run with: uv run pytest -m lab tests/integration/test_nautobot.py
First boot takes ~2.5 minutes on a desktop (database migrations).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from labutil import service_session

from llm_on_a_stick import lab, services
from llm_on_a_stick.services import lifecycle, seed

pytestmark = pytest.mark.lab


@pytest.fixture(scope="module")
def nautobot() -> Iterator[seed.RestClient]:
    with service_session("nautobot") as spec:
        assert spec.seed is not None
        lifecycle.restore_snapshot(spec)  # start from the baseline, whatever an earlier run left behind
        yield seed.RestClient(spec.seed.base_url, spec.seed.headers)
        lifecycle.restore_snapshot(spec)  # leave its data at the baseline for next time


def count(client: seed.RestClient, path: str) -> int:
    return int(client.get(path)["count"])


def test_seeded_baseline(nautobot: seed.RestClient) -> None:
    assert count(nautobot, "dcim/locations/?name=stick-lab") == 1
    assert count(nautobot, "extras/roles/?content_types=dcim.device") == 3
    assert count(nautobot, "dcim/platforms/?name=SR Linux".replace(" ", "%20")) == 1
    assert count(nautobot, "ipam/prefixes/?prefix=172.30.30.0/24&namespace=stick-lab") == 1
    assert count(nautobot, "dcim/devices/") == 0  # documenting the lab is a task, not seed data


def test_api_wants_token_not_bearer(nautobot: seed.RestClient) -> None:
    token = nautobot.headers["Authorization"].split(" ", 1)[1]
    bearer = seed.RestClient(nautobot.base_url, {"Authorization": f"Bearer {token}"})
    with pytest.raises(seed.RestError, match="HTTP 403"):
        bearer.get("dcim/devices/")


def test_reachable_from_lab_network(nautobot: seed.RestClient) -> None:
    ip = lab.SERVICE_IPS["nautobot"]
    res = subprocess.run(
        ["docker", "run", "--rm", "--network", lab.MGMT_NETWORK, "curlimages/curl:8.17.0",
         "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://{ip}:8080/health/"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.stdout.strip() == "200"


def test_reset_removes_changes(nautobot: seed.RestClient) -> None:
    spec = services.load("nautobot")
    nautobot.post(
        "dcim/devices/",
        {
            "name": "srl1",
            "role": {"name": "Spine"},
            "device_type": {"model": "7220 IXR-D2L"},
            "location": {"name": "stick-lab"},
            "status": {"name": "Active"},
        },
    )
    assert count(nautobot, "dcim/devices/?name=srl1") == 1

    lifecycle.restore_snapshot(spec)

    assert count(nautobot, "dcim/devices/") == 0
    assert count(nautobot, "dcim/locations/?name=stick-lab") == 1


def test_reset_is_repeatable(nautobot: seed.RestClient) -> None:
    spec = services.load("nautobot")
    paths = ("dcim/locations/", "dcim/device-types/", "dcim/platforms/", "ipam/namespaces/")
    before = [count(nautobot, p) for p in paths]
    lifecycle.restore_snapshot(spec)
    lifecycle.restore_snapshot(spec)
    after = [count(nautobot, p) for p in paths]
    assert before == after
