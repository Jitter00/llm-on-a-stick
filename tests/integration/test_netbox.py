"""NetBox service: up -> seeded -> agent-style change -> reset restores the baseline.

Run with: uv run pytest -m lab tests/integration/test_netbox.py
First boot takes ~2.5 minutes (database migrations).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from labutil import check_mcp_server, service_session

from llm_on_a_stick import lab, services
from llm_on_a_stick.services import lifecycle, seed

pytestmark = pytest.mark.lab


@pytest.fixture(scope="module")
def netbox() -> Iterator[seed.RestClient]:
    with service_session("netbox") as spec:
        assert spec.seed is not None
        lifecycle.restore_snapshot(spec)  # start from the baseline, whatever an earlier run left behind
        yield seed.RestClient(spec.seed.base_url, spec.seed.headers)
        lifecycle.restore_snapshot(spec)  # leave its data at the baseline for next time


def count(client: seed.RestClient, path: str) -> int:
    return int(client.get(path)["count"])


def test_seeded_baseline(netbox: seed.RestClient) -> None:
    assert count(netbox, "dcim/sites/?slug=stick-lab") == 1
    assert count(netbox, "dcim/device-roles/") == 3
    assert count(netbox, "dcim/platforms/?slug=srlinux") == 1
    assert count(netbox, "dcim/devices/") == 0  # documenting the lab is a task, not seed data


def test_reachable_from_lab_network(netbox: seed.RestClient) -> None:
    ip = lab.SERVICE_IPS["netbox"]
    res = subprocess.run(
        ["docker", "run", "--rm", "--network", lab.MGMT_NETWORK, "curlimages/curl:8.17.0",
         "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://{ip}:8080/login/"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.stdout.strip() == "200"


def test_reset_removes_changes(netbox: seed.RestClient) -> None:
    spec = services.load("netbox")
    netbox.post(
        "dcim/devices/",
        {
            "name": "srl1",
            "role": {"slug": "spine"},
            "device_type": {"slug": "7220-ixr-d2l"},
            "site": {"slug": "stick-lab"},
        },
    )
    assert count(netbox, "dcim/devices/?name=srl1") == 1

    lifecycle.restore_snapshot(spec)

    assert count(netbox, "dcim/devices/") == 0
    assert count(netbox, "dcim/sites/?slug=stick-lab") == 1


def test_reset_is_repeatable(netbox: seed.RestClient) -> None:
    spec = services.load("netbox")
    before = [count(netbox, p) for p in ("dcim/sites/", "dcim/device-types/", "dcim/platforms/")]
    lifecycle.restore_snapshot(spec)
    lifecycle.restore_snapshot(spec)
    after = [count(netbox, p) for p in ("dcim/sites/", "dcim/device-types/", "dcim/platforms/")]
    assert before == after


def test_its_mcp_server_starts_and_answers(netbox: seed.RestClient) -> None:
    check_mcp_server("netbox", "netbox_get_objects", {"object_type": "dcim.site", "filters": {}}, "stick-lab")
