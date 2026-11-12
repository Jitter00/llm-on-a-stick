"""Zabbix against the live base lab: the API token, polling both router OSes over SNMP, port discovery, a
trigger that raises a problem, a maintenance that takes effect, and reset.

Run with: uv run pytest -m lab tests/integration/test_zabbix.py
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from typing import Any

import pytest
from labutil import check_mcp_server, service_session, wait_for

from llm_on_a_stick import lab as lab_consts
from llm_on_a_stick import services
from llm_on_a_stick.grading import zabbixstate as state
from llm_on_a_stick.services import lifecycle, seed

pytestmark = pytest.mark.lab

SRL1, FRR1 = "172.30.30.11", "172.30.30.21"
TEMPLATE = "Network Generic Device by SNMP"


@pytest.fixture(scope="module")
def zabbix(lab: None) -> Iterator[seed.RestClient]:
    with service_session("zabbix") as spec:
        lifecycle.restore_snapshot(spec)  # start from the baseline, whatever an earlier run left behind
        api = spec.api_settings
        assert api is not None
        yield seed.RestClient(api.base_url, api.headers)
        lifecycle.restore_snapshot(spec)


def add(api: seed.RestClient, host: str, ip: str, community: str = "stick-ro") -> str:
    group = state.rpc(api, "hostgroup.get", {"output": ["groupid"], "filter": {"name": ["Routers"]}})
    template = state.rpc(api, "template.get", {"output": ["templateid"], "filter": {"host": [TEMPLATE]}})
    interface = {"type": 2, "main": 1, "useip": 1, "ip": ip, "dns": "", "port": "161",
                 "details": {"version": 2, "bulk": 1, "community": "{$SNMP_COMMUNITY}"}}  # fmt: skip
    made = state.rpc(
        api, "host.create",
        {"host": host, "groups": [{"groupid": group[0]["groupid"]}],
         "templates": [{"templateid": template[0]["templateid"]}],
         "macros": [{"macro": "{$SNMP_COMMUNITY}", "value": community}], "interfaces": [interface]},
    )  # fmt: skip
    return str(made["hostids"][0])


def host(api: seed.RestClient, name: str) -> dict[str, Any]:
    return next(h for h in state.hosts(api) if h["host"] == name)


def test_starts_empty_and_the_token_works(zabbix: seed.RestClient) -> None:
    assert state.rpc(zabbix, "apiinfo.version").startswith("8.0")
    snap = state.snapshot(zabbix)
    assert snap["hosts"] == {} and snap["triggers"] == {} and snap["maintenances"] == {}
    assert "Routers" in [g["label"] for g in snap["groups"].values()]
    assert snap["macros"]["{$SNMP_COMMUNITY}"]["value"] == "not-a-lab-community"  # no fallback to "public"


def test_errors_come_with_http_200(zabbix: seed.RestClient) -> None:
    with pytest.raises(state.ZabbixError, match=r"host\.nope"):
        state.rpc(zabbix, "host.nope")


def test_polls_sr_linux_and_frr_and_notices_a_wrong_community(zabbix: seed.RestClient) -> None:
    ids = [add(zabbix, "srl1", SRL1), add(zabbix, "frr1", FRR1), add(zabbix, "srl2", "172.30.30.12", "wrong")]
    state.refresh(zabbix, ids)
    # Zabbix takes any community: a wrong one only shows as an interface it can't reach.
    assert wait_for(
        lambda: [host(zabbix, n)["available"] for n in ("srl1", "frr1", "srl2")] == [1, 1, 2],
        timeout=90, interval=3,
    ), [host(zabbix, n) for n in ("srl1", "frr1", "srl2")]  # fmt: skip
    assert host(zabbix, "srl2")["community"] == "wrong" and host(zabbix, "srl1")["community"] == "stick-ro"


def test_discovers_ports_with_their_descriptions(zabbix: seed.RestClient) -> None:
    hostid = host(zabbix, "srl1")["hostid"]
    rules = state.rpc(
        zabbix, "discoveryrule.get",
        {"hostids": [hostid], "output": ["itemid"], "filter": {"key_": "net.if.discovery"}},
    )  # fmt: skip

    def port_items() -> list[dict[str, Any]]:
        return list(
            state.rpc(
                zabbix, "item.get",
                {"hostids": [hostid], "output": ["name", "key_"], "search": {"key_": "net.if.status"}},
            )
        )  # fmt: skip

    state.poll_now(zabbix, [rules[0]["itemid"]])
    assert wait_for(lambda: bool(port_items()), timeout=90, interval=3)
    names = {i["name"]: i["key_"] for i in port_items()}
    # The interface description from the startup config is in the item's name; the key has the ifIndex.
    assert names["Interface ethernet-1/1(to frr1): Operational status"] == "net.if.status[ifOperStatus.32768]"


def test_trigger_raises_a_problem_after_a_forced_poll(zabbix: seed.RestClient) -> None:
    key = "net.if.status[ifOperStatus.32768]"  # ethernet-1/1, which is up (1)
    made = state.rpc(
        zabbix, "trigger.create",
        {"description": "stick-test-up", "priority": 4, "expression": f"last(/srl1/{key})=1"},
    )  # fmt: skip
    triggerid = made["triggerids"][0]
    assert [t["description"] for t in state.triggers(zabbix)] == ["stick-test-up"]  # not the template's
    items = state.rpc(zabbix, "item.get", {"triggerids": [triggerid], "output": ["itemid"]})
    state.poll_now(zabbix, [i["itemid"] for i in items])
    assert wait_for(
        lambda: bool(state.rpc(zabbix, "problem.get", {"objectids": [triggerid], "output": ["eventid"]})),
        timeout=60, interval=2,
    )  # fmt: skip


def test_maintenance_takes_effect_within_a_minute_or_so(zabbix: seed.RestClient) -> None:
    now = int(time.time())
    state.rpc(
        zabbix, "maintenance.create",
        {"name": "stick-test-window", "maintenance_type": 1, "active_since": now, "active_till": now + 3600,
         "hosts": [{"hostid": host(zabbix, "frr1")["hostid"]}],
         "timeperiods": [{"timeperiod_type": 0, "start_date": now, "period": 3600}]},
    )  # fmt: skip
    state.reload_config()
    assert wait_for(lambda: host(zabbix, "frr1")["maintenance"] == 1, timeout=120, interval=3)
    assert host(zabbix, "frr1")["maintenance_type"] == 1 and host(zabbix, "srl1")["maintenance"] == 0


def test_reset_restores_the_empty_baseline(zabbix: seed.RestClient) -> None:
    assert state.hosts(zabbix)
    lifecycle.restore_snapshot(services.load("zabbix"))
    snap = state.snapshot(zabbix)
    assert snap["hosts"] == {} and snap["triggers"] == {} and snap["maintenances"] == {}


def test_reachable_from_the_lab_network(zabbix: seed.RestClient) -> None:
    url = f"http://{lab_consts.SERVICE_EXTRA_IPS['zabbix'][0]}:8080/api_jsonrpc.php"
    body = '{"jsonrpc": "2.0", "method": "apiinfo.version", "params": {}, "id": 1}'
    res = subprocess.run(
        ["docker", "exec", "clab-stick-base-h1", "curl", "-sf", "-H", "Content-Type: application/json",
         "--data", body, url],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert '"result":"8.0' in res.stdout, res.stderr


def test_its_mcp_server_starts_and_answers(zabbix: seed.RestClient) -> None:
    check_mcp_server("zabbix", "hostgroup_get", {}, "Zabbix servers")
