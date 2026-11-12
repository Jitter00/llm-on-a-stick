"""LibreNMS against the live base lab: the API token, adding and polling both router OSes, an alert rule
that fires, and reset.

Run with: uv run pytest -m lab tests/integration/test_librenms.py
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from labutil import check_mcp_server, service_session, wait_for

from llm_on_a_stick import lab as lab_consts
from llm_on_a_stick import services
from llm_on_a_stick.grading import librenmsstate as state
from llm_on_a_stick.services import lifecycle, seed

pytestmark = pytest.mark.lab

SRL1, FRR1 = "172.30.30.11", "172.30.30.21"


@pytest.fixture(scope="module")
def librenms(lab: None) -> Iterator[seed.RestClient]:
    with service_session("librenms") as spec:
        lifecycle.restore_snapshot(spec)  # start from the baseline, whatever an earlier run left behind
        api = spec.api_settings
        assert api is not None
        yield seed.RestClient(api.base_url, api.headers)
        lifecycle.restore_snapshot(spec)


def add(client: seed.RestClient, hostname: str, community: str = "stick-ro", **extra: object) -> object:
    body = {"hostname": hostname, "version": "v2c", "community": community, **extra}
    return client.post("devices", body)


def test_starts_empty_and_the_token_works(librenms: seed.RestClient) -> None:
    assert librenms.get("system")["status"] == "ok"
    assert state.devices(librenms) == []
    assert state.snapshot(librenms) == {"devices": {}, "rules": {}, "groups": {}}


def test_wrong_community_is_refused_not_replaced_by_public(librenms: seed.RestClient) -> None:
    with pytest.raises(seed.RestError, match="SNMP"):
        add(librenms, SRL1, community="wrong")
    assert state.devices(librenms) == []


def test_polls_sr_linux_and_frr(librenms: seed.RestClient) -> None:
    add(librenms, SRL1)
    add(librenms, FRR1)
    state.refresh(librenms)
    by_host = {d["hostname"]: d for d in state.devices(librenms)}
    assert by_host[SRL1]["os"] == "srlinux" and by_host[SRL1]["status"] == 1
    assert by_host[SRL1]["sysName"] == "srl1" and by_host[SRL1]["hardware"] == "7220 IXR-D2L"
    assert (
        by_host[FRR1]["os"] == "linux" and by_host[FRR1]["status"] == 1 and by_host[FRR1]["sysName"] == "frr1"
    )
    ports = {p["ifName"]: p for p in librenms.get(f"devices/{SRL1}/ports?columns=ifName,ifAlias")["ports"]}
    assert ports["ethernet-1/1"]["ifAlias"] == "to frr1"  # the interface description, from the startup config


def test_dispatcher_discovers_a_new_device_on_its_own(librenms: seed.RestClient) -> None:
    add(librenms, "172.30.30.12")
    assert wait_for(
        lambda: bool(librenms.get("devices/172.30.30.12")["devices"][0].get("last_discovered")),
        timeout=90, interval=3,
    )  # fmt: skip


def test_alert_rule_fires_on_poll(librenms: seed.RestClient) -> None:
    condition = {"id": "ports.ifOperStatus", "field": "ports.ifOperStatus", "type": "string", "input": "text",
                 "operator": "equal", "value": "down"}  # fmt: skip
    builder = {"condition": "AND", "rules": [condition], "valid": True}
    rule = {"name": "stick-test-down", "devices": [-1], "severity": "warning", "count": 1, "delay": 0,
            "interval": 300, "mute": False, "builder": builder}  # fmt: skip
    try:
        librenms.post("rules", rule)
    except seed.RestError as exc:  # 26.10 creates the rule and still complains about transports
        assert "transport" in str(exc)
    rules = [r for r in state.listing(librenms, "rules", "rules") if r["name"] == "stick-test-down"]
    assert len(rules) == 1
    state.refresh(librenms)
    alerts = [
        a for a in state.listing(librenms, "alerts?state=1", "alerts") if a["rule_id"] == rules[0]["id"]
    ]
    assert alerts, "no alert for the down ports"  # SR Linux has dozens of unused ports, all down


def test_reset_restores_the_empty_baseline(librenms: seed.RestClient) -> None:
    assert state.devices(librenms)
    lifecycle.restore_snapshot(services.load("librenms"))
    assert state.devices(librenms) == [] and state.listing(librenms, "rules", "rules") == []


def test_reachable_from_the_lab_network(librenms: seed.RestClient) -> None:
    url = f"http://{lab_consts.SERVICE_IPS['librenms']}:8000/api/v0/system"
    res = subprocess.run(
        ["docker", "exec", "clab-stick-base-h1", "curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}",
         "-H", f"X-Auth-Token: {librenms.headers['X-Auth-Token']}", url],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.stdout.strip() == "200", res.stderr


def test_its_mcp_server_starts_and_answers(librenms: seed.RestClient) -> None:
    check_mcp_server("librenms", "system_info", {}, "local_ver")
