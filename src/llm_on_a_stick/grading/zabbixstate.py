"""Zabbix for grading: the JSON-RPC API, make the server look at hosts now, a snapshot of what a task may
touch, and what changed since.

Zabbix polls on its own schedule (a port's status every minute, new configuration every few seconds). The
grader doesn't wait for that: it has the server reload its configuration and poll the items it needs
("execute now"), then waits for the result it is looking for, so a pass is quick and a fail waits `wait_s`.

`stick task start` saves the snapshot to baseline/zabbix.json right after setup; the `zabbix_unchanged` check
compares it with the service at grading time.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import Any, Protocol

from llm_on_a_stick import services
from llm_on_a_stick.grading.librenmsstate import diff as diff  # the same rules: kind / kind:label allow lists
from llm_on_a_stick.services import lifecycle

SERVICE = "zabbix"
CONTAINER = "server"  # the compose service that polls
SNMP_INTERFACE = "2"  # hostinterface.type
SNMP_ITEM = 20  # item.type "SNMP agent"
EXECUTE_NOW = 6  # task.type "check now"

Snapshot = dict[str, dict[str, dict[str, Any]]]  # kind -> id -> object


class ZabbixError(RuntimeError):
    pass


class Api(Protocol):
    def post(self, path: str, body: Any) -> Any: ...


def rpc(api: Api, method: str, params: Any = None) -> Any:
    """One JSON-RPC call. Zabbix answers errors with HTTP 200 and an `error` object."""
    reply = api.post("api_jsonrpc.php", {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1})
    if not isinstance(reply, dict) or "result" not in reply:
        error = (reply or {}).get("error", reply) if isinstance(reply, dict) else reply
        raise ZabbixError(f"{method}: {error}")
    return reply["result"]


def reload_config() -> None:
    """Have the server read the configuration from the database now (hosts, items and triggers just made)."""
    argv = lifecycle.compose_argv(
        services.load(SERVICE), "exec", "-T", CONTAINER, "zabbix_server", "-R", "config_cache_reload"
    )
    try:
        res = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ZabbixError(f"cannot reload the Zabbix server's configuration: {exc}") from exc
    if res.returncode != 0:
        raise ZabbixError(f"cannot reload the Zabbix server's configuration: {res.stderr.strip()[-200:]}")


def poll_now(api: Api, itemids: list[str]) -> None:
    """Ask the server to poll these items now. Zabbix refuses items it can't poll on request (disabled,
    on a disabled host, trapper items...): those are left out, one refusal at a time."""
    reload_config()
    time.sleep(1)  # the reload is asynchronous; a task for an item the server doesn't know yet is dropped
    for itemid in itemids:
        try:
            rpc(api, "task.create", [{"type": EXECUTE_NOW, "request": {"itemid": itemid}}])
        except ZabbixError:
            continue


def wait_for(probe: Callable[[], bool], wait_s: float, every_s: float = 2) -> bool:
    deadline = time.monotonic() + wait_s
    while True:
        if probe():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(every_s)


def _macros(api: Api) -> dict[str, str]:
    found = rpc(api, "usermacro.get", {"globalmacro": True, "output": ["macro", "value"]})
    return {m["macro"]: m.get("value", "") for m in found}


def hosts(api: Api) -> list[dict[str, Any]]:
    """Every host, flattened to what tasks and checks talk about. `ip`, `community` and `available` are
    those of its main SNMP interface (None without one); a community given as a macro is resolved from the
    host's macros, then the global ones. `available`: 0 not known yet, 1 reached, 2 not reached."""
    global_macros = _macros(api)
    out = []
    for h in rpc(
        api, "host.get",
        {
            "output": ["hostid", "host", "name", "status", "maintenance_status", "maintenance_type",
                       "maintenanceid"],
            "selectInterfaces": ["type", "main", "useip", "ip", "dns", "port", "details", "available",
                                 "error"],
            "selectMacros": ["macro", "value"],
            "selectHostGroups": ["name"],
            "selectParentTemplates": ["host"],
            "selectTags": ["tag", "value"],
        },
    ):  # fmt: skip
        macros = {m["macro"]: m.get("value", "") for m in h.get("macros") or []}
        snmp = [i for i in h.get("interfaces") or [] if str(i.get("type")) == SNMP_INTERFACE]
        snmp.sort(key=lambda i: str(i.get("main")) != "1")
        main = snmp[0] if snmp else {}
        raw = main.get("details")
        details: dict[str, Any] = raw if isinstance(raw, dict) else {}
        community = details.get("community")
        if isinstance(community, str) and community.startswith("{$"):
            community = macros.get(community, global_macros.get(community, community))
        out.append(
            {
                "hostid": str(h["hostid"]),
                "host": h["host"],
                "name": h.get("name"),
                "status": int(h.get("status", 0)),  # 0 monitored, 1 not
                "ip": main.get("ip"),
                "port": main.get("port"),
                "snmp_version": details.get("version"),
                "community": community,
                "available": int(main["available"]) if snmp else None,
                "error": main.get("error", ""),
                "groups": sorted(g["name"] for g in h.get("hostgroups") or []),
                "templates": sorted(t["host"] for t in h.get("parentTemplates") or []),
                "tags": sorted(f"{t['tag']}={t.get('value', '')}" for t in h.get("tags") or []),
                "macros": macros,
                "interfaces": sorted(
                    f"{i.get('type')}:{i.get('ip') or i.get('dns')}:{i.get('port')}"
                    for i in h.get("interfaces") or []
                ),
                "maintenance": int(h.get("maintenance_status", 0)),  # 1 while in a maintenance
                "maintenance_type": int(h.get("maintenance_type", 0)),  # 1 = without data collection
                "maintenanceid": str(h.get("maintenanceid", "0")),
            }
        )
    return out


def refresh(api: Api, hostids: list[str]) -> None:
    """Poll the SNMP items of these hosts now, which is also what tells Zabbix whether it reaches them."""
    if not hostids:
        reload_config()
        return
    items = rpc(
        api, "item.get",
        {"hostids": hostids, "output": ["itemid"], "filter": {"type": SNMP_ITEM, "status": 0}, "limit": 40},
    )  # fmt: skip
    poll_now(api, [i["itemid"] for i in items])


def triggers(api: Api, name: str | None = None) -> list[dict[str, Any]]:
    """The triggers people made on hosts: not the templates' ones, nor those discovery made from them."""
    params: dict[str, Any] = {
        "output": ["triggerid", "description", "priority", "status", "expression", "value"],
        "expandExpression": True,
        "templated": False,
        "inherited": False,
        "selectHosts": ["hostid", "host"],
        "filter": {"flags": 0},
    }
    if name is not None:
        params["filter"]["description"] = name
    return list(rpc(api, "trigger.get", params))


def maintenances(api: Api) -> list[dict[str, Any]]:
    return list(
        rpc(
            api, "maintenance.get",
            {
                "output": ["maintenanceid", "name", "maintenance_type", "active_since", "active_till"],
                "selectHostGroups": ["groupid", "name"],
                "selectHosts": ["hostid", "host"],
                "selectTimeperiods": ["timeperiod_type", "start_date", "period"],
            },
        )
    )  # fmt: skip


HOST_FIELDS = (
    "name", "status", "ip", "port", "snmp_version", "community", "groups", "templates", "tags", "macros",
    "interfaces",
)  # fmt: skip


def snapshot(api: Api) -> Snapshot:
    """Hosts (how they are monitored, not what polling found), the triggers people made, maintenances, host
    groups and global macros."""
    return {
        "hosts": {h["hostid"]: {"label": h["host"], **{k: h[k] for k in HOST_FIELDS}} for h in hosts(api)},
        "triggers": {
            str(t["triggerid"]): {
                "label": t["description"],
                **{k: t.get(k) for k in ("priority", "status", "expression")},
            }
            for t in triggers(api)
        },
        "maintenances": {
            str(m["maintenanceid"]): {
                "label": m["name"],
                "type": m.get("maintenance_type"),
                "active_since": m.get("active_since"),
                "active_till": m.get("active_till"),
                "groups": sorted(g["name"] for g in m.get("hostgroups") or []),
                "hosts": sorted(h["host"] for h in m.get("hosts") or []),
                "timeperiods": m.get("timeperiods") or [],
            }
            for m in maintenances(api)
        },
        "groups": {
            str(g["groupid"]): {"label": g["name"]}
            for g in rpc(api, "hostgroup.get", {"output": ["groupid", "name"]})
        },
        "macros": {macro: {"label": macro, "value": value} for macro, value in _macros(api).items()},
    }
