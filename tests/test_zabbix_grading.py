"""Unit tests for the Zabbix section: the service definition, the state snapshot and the checks.

No Docker: the JSON-RPC API is a fake, and the server's reload and the waiting are replaced.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import paths, services
from llm_on_a_stick.grading import run
from llm_on_a_stick.grading import zabbixstate as state
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.spec import MysqlSnapshot
from llm_on_a_stick.tasks import load_task
from test_grading import FakeLab, check, make_ctx

TASK = paths.sections_dir() / "zabbix" / "zabbix-fix-monitoring"
TOKEN = "0123456789abcdef" * 4


class FakeZabbix:
    """The JSON-RPC methods the grader calls. "Execute now" on an item turns its host's pending values in:
    a host's `pending` availability, a trigger's `pending` problem."""

    def __init__(self) -> None:
        self.hosts: list[dict[str, Any]] = []
        self.triggers: list[dict[str, Any]] = []
        self.maintenances: list[dict[str, Any]] = []
        self.problems: list[dict[str, Any]] = []
        self.globals = {"{$SNMP_COMMUNITY}": "not-a-lab-community"}
        self.polled: list[str] = []

    def add(self, host: str, ip: str, community: str = "{$SNMP_COMMUNITY}", **fields: Any) -> dict[str, Any]:
        hostid = str(10800 + len(self.hosts))
        obj = {
            "hostid": hostid, "host": host, "name": host, "status": "0", "maintenance_status": "0",
            "maintenance_type": "0", "maintenanceid": "0",
            "interfaces": [{"type": "2", "main": "1", "useip": "1", "ip": ip, "dns": "", "port": "161",
                            "available": "1", "error": "",
                            "details": {"version": "2", "bulk": "1", "community": community}}],
            "macros": [{"macro": "{$SNMP_COMMUNITY}", "value": "stick-ro"}],
            "hostgroups": [{"name": "Routers"}],
            "parentTemplates": [{"host": "Network Generic Device by SNMP"}],
            "tags": [],
            **fields,
        }  # fmt: skip
        self.hosts.append(obj)
        return obj

    def post(self, path: str, body: dict[str, Any]) -> Any:
        assert path == "api_jsonrpc.php" and body["jsonrpc"] == "2.0"
        method, params = body["method"], body["params"]
        handler = getattr(self, "_" + method.replace(".", "_"), None)
        if handler is None:
            return {"jsonrpc": "2.0", "error": {"code": -32602, "data": f"no method {method}"}, "id": 1}
        return {"jsonrpc": "2.0", "result": handler(params), "id": 1}

    def _host_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.hosts

    def _usermacro_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"macro": k, "value": v} for k, v in self.globals.items()]

    def _hostgroup_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        names = sorted({g["name"] for h in self.hosts for g in h["hostgroups"]} | {"Routers"})
        return [{"groupid": str(n + 20), "name": name} for n, name in enumerate(names)]

    def _trigger_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        name = params["filter"].get("description")
        return [t for t in self.triggers if name in (None, t["description"])]

    def _maintenance_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.maintenances

    def _item_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "triggerids" in params:
            return [{"itemid": f"t{tid}"} for tid in params["triggerids"]]
        return [{"itemid": f"h{hostid}"} for hostid in params["hostids"]]

    def _task_create(self, params: list[dict[str, Any]]) -> dict[str, Any]:
        itemid = params[0]["request"]["itemid"]
        self.polled.append(itemid)
        for host in self.hosts:
            if itemid == f"h{host['hostid']}" and "pending" in host:
                host["interfaces"][0]["available"] = host.pop("pending")
        for trig in self.triggers:
            if itemid == f"t{trig['triggerid']}":
                self.problems += [{"eventid": "1", "objectid": trig["triggerid"]}] * trig.pop("pending", 0)
        return {"taskids": ["1"]}

    def _problem_get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [p for p in self.problems if p["objectid"] in params["objectids"]]


class FakeServices:
    def __init__(self, api: FakeZabbix) -> None:
        self.api = api

    def rest(self, name: str) -> FakeZabbix:
        assert name == "zabbix"
        return self.api


@pytest.fixture
def zbx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FakeZabbix]:
    api = FakeZabbix()
    ctx = make_ctx(tmp_path)
    ctx.services = FakeServices(api)  # type: ignore[assignment]
    monkeypatch.setattr(state, "reload_config", lambda: None)
    monkeypatch.setattr(state.time, "sleep", lambda s: None)
    monkeypatch.setattr(state, "wait_for", lambda probe, wait_s, every_s=2: probe())
    return ctx, api


# --------------------------------------------------------------------------- the service


def test_zabbix_service_definition() -> None:
    spec = services.load("zabbix", env={})
    assert isinstance(spec.snapshot, MysqlSnapshot)
    assert spec.snapshot.stop == ["server"]  # not loaded under a running server
    assert spec.seed is None and spec.api_settings is not None
    assert spec.api_settings.base_url == "http://127.0.0.1:8085/"
    assert (
        spec.api_settings.headers["Authorization"]
        == f"Bearer {TOKEN}"
        == spec.health.headers["Authorization"]
    )
    # JSON-RPC answers 200 to everything: healthy = a call made with the token has a result.
    assert spec.health.post is not None and spec.health.post["method"] == "host.get"
    assert spec.health.expect == '"result"'
    assert spec.init is not None and spec.init.restart == ["server"]
    steps = [" ".join(s.cmd) for s in spec.init.steps]
    assert "SHA2(" in steps[0] and "not-a-lab-community" in steps[0]  # the token; no fallback to "public"
    assert "host.delete" in steps[1] and "hostgroup.create" in steps[1]
    assert services.load("zabbix", env={"STICK_ZABBIX_PORT": "9000"}).health.url.startswith(
        "http://127.0.0.1:9000/"
    )


def test_service_vars_give_the_zabbix_token() -> None:
    values = run.service_vars()["zabbix"]
    assert values == {"url": "http://127.0.0.1:8085", "auth": f"Bearer {TOKEN}", "token": TOKEN}


def test_health_can_post_and_look_for_text(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = services.load("zabbix", env={})
    seen: list[Any] = []

    class Reply:
        status = 200

        def __init__(self, text: str) -> None:
            self.text = text

        def read(self) -> bytes:
            return self.text.encode()

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    replies = [
        '{"jsonrpc":"2.0","error":{"data":"Not authorized."},"id":1}',
        '{"jsonrpc":"2.0","result":"0"}',
    ]

    def urlopen(req: Any, timeout: float) -> Reply:
        seen.append(req)
        return Reply(replies.pop(0))

    monkeypatch.setattr(lifecycle.urllib.request, "urlopen", urlopen)
    assert not lifecycle.healthy(spec)  # HTTP 200, but an error inside: the token isn't there yet
    assert lifecycle.healthy(spec)
    assert seen[0].get_method() == "POST" and json.loads(seen[0].data)["method"] == "host.get"
    assert seen[0].get_header("Content-type") == "application/json"


def test_reset_stops_the_server_around_the_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = services.load("zabbix", env={})
    calls: list[list[str]] = []
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(lifecycle, "wait_healthy", lambda spec, timeout: None)
    lifecycle.restore_snapshot(spec)
    stop, restore, up = [c for c in calls if "test" not in c]  # minus the has_snapshot probe
    assert stop[-2:] == ["stop", "server"]
    assert restore[-1].startswith('mariadb -u"$SNAP_USER"') and "MYSQL_PWD=stick-zabbix-db" in restore
    assert "up" in up and "--wait" in up


# --------------------------------------------------------------------------- the API, snapshot and diff


def test_rpc_raises_on_an_error_answer() -> None:
    api = FakeZabbix()
    assert state.rpc(api, "host.get") == []
    with pytest.raises(state.ZabbixError, match=r"no method nope\.get"):
        state.rpc(api, "nope.get")


def test_hosts_resolve_the_community_macro() -> None:
    api = FakeZabbix()
    api.add("srl1", "172.30.30.11")
    api.add("srl2", "172.30.30.12", community="literal")
    api.add("frr1", "172.30.30.21", macros=[])
    api.add("agent-only", "", interfaces=[{"type": "1", "main": "1", "ip": "10.0.0.1", "port": "10050"}])
    by_name = {h["host"]: h for h in state.hosts(api)}
    assert by_name["srl1"]["community"] == "stick-ro" and by_name["srl1"]["ip"] == "172.30.30.11"
    assert by_name["srl2"]["community"] == "literal"
    assert by_name["frr1"]["community"] == "not-a-lab-community"  # the global macro
    assert by_name["agent-only"]["ip"] is None and by_name["agent-only"]["available"] is None
    assert by_name["srl1"]["groups"] == ["Routers"] and by_name["srl1"]["available"] == 1


def test_snapshot_keeps_how_a_host_is_monitored_not_what_polling_found() -> None:
    api = FakeZabbix()
    api.add("srl1", "172.30.30.11")
    api.triggers.append({"triggerid": "7", "description": "t", "priority": "4", "status": "0",
                         "expression": "last(/srl1/x)=2", "hosts": [{"host": "srl1"}]})  # fmt: skip
    before = json.loads(json.dumps(state.snapshot(api)))
    assert set(before) == {"hosts", "triggers", "maintenances", "groups", "macros"}
    assert before["hosts"]["10800"]["label"] == "srl1" and "available" not in before["hosts"]["10800"]
    api.hosts[0]["interfaces"][0]["available"] = "2"  # polling found it down: not an edit
    api.hosts[0]["maintenance_status"] = "1"  # nor is being in a maintenance
    assert state.diff(before, state.snapshot(api), [], [], []) == []
    api.hosts[0]["macros"][0]["value"] = "other"
    api.triggers[0]["priority"] = "2"
    api.globals["{$SNMP_COMMUNITY}"] = "stick-ro"
    assert state.diff(before, state.snapshot(api), [], [], []) == [
        "hosts: changed srl1 (community, macros)",
        "triggers: changed t (priority)",
        "macros: changed {$SNMP_COMMUNITY} (value)",
    ]
    assert state.diff(before, state.snapshot(api), [], ["hosts:srl1", "triggers", "macros"], []) == []


def test_diff_sees_a_deleted_and_re_added_host() -> None:
    api = FakeZabbix()
    api.add("srl2", "172.30.30.12")
    before = state.snapshot(api)
    api.hosts[0]["hostid"] = "10999"
    assert state.diff(before, state.snapshot(api), ["hosts"], [], []) == ["hosts: deleted srl2"]


# --------------------------------------------------------------------------- checks


def test_zabbix_host_polls_then_compares(zbx: tuple[Any, FakeZabbix]) -> None:
    ctx, api = zbx
    res = check(ctx, "zabbix_host", ip="172.30.30.11", expect={"available": 1})
    assert res.status == "fail" and res.hints == ["missing-object"]
    host = api.add("stick-abc", "172.30.30.11", community="stick-x", pending="1")
    host["interfaces"][0].update(available="0")
    expect = {"host": "stick-abc", "status": 0, "available": 1, "snmp_version": 2, "community": "stick-x",
              "groups": ["Routers"], "templates": ["Network Generic Device by SNMP"]}  # fmt: skip
    assert check(ctx, "zabbix_host", ip="172.30.30.11", expect=expect).status == "pass"
    assert api.polled == ["h10800"]
    host["interfaces"][0].update(available="2", error="Timeout while connecting")
    res = check(ctx, "zabbix_host", ip="172.30.30.11", expect={**expect, "groups": ["Routers", "Core"]})
    assert res.status == "fail" and res.hints == ["wrong-config"] and "2 of 7" in res.message
    assert res.observed == {"available": 2, "groups": ["Routers"], "error": "Timeout while connecting"}
    assert check(ctx, "zabbix_absent", ip="172.30.30.11").hints == ["collateral-change"]
    assert check(ctx, "zabbix_absent", ip="172.30.30.12").status == "pass"


def test_zabbix_problem_wants_one_trigger_in_problem_state(zbx: tuple[Any, FakeZabbix]) -> None:
    ctx, api = zbx
    params = {"trigger": "my trigger", "hosts": ["srl1"], "severity": 4}
    assert check(ctx, "zabbix_problem", **params).hints == ["missing-object"]
    trig = {"triggerid": "7", "description": "my trigger", "priority": "3", "status": "0",
            "expression": "last(/srl2/net.if.status[ifOperStatus.1])=2",
            "hosts": [{"host": "srl2"}]}  # fmt: skip
    api.triggers.append(trig)
    assert "severity" in check(ctx, "zabbix_problem", **params).message
    trig["priority"] = "4"
    res = check(ctx, "zabbix_problem", **params)
    assert res.status == "fail" and "host" in res.message and res.observed["hosts"] == ["srl2"]
    trig["hosts"] = [{"host": "srl1"}]
    res = check(ctx, "zabbix_problem", **params)
    assert res.status == "fail" and res.observed["problems"] == 0 and api.polled == ["t7"]
    trig["pending"] = 1
    assert check(ctx, "zabbix_problem", **params).status == "pass"
    trig["status"] = "1"
    assert "disabled" in check(ctx, "zabbix_problem", **params).message
    trig["status"] = "0"
    api.triggers.append({**trig, "triggerid": "8"})  # a duplicate
    assert "exactly one" in check(ctx, "zabbix_problem", **params).message


def test_zabbix_maintenance_checks_the_window_and_who_is_in_it(zbx: tuple[Any, FakeZabbix]) -> None:
    ctx, api = zbx
    srl1, srl2 = api.add("srl1", "172.30.30.11"), api.add("srl2", "172.30.30.12")
    params = {"name": "win", "hosts": ["srl1"], "duration_s": 7200}
    assert check(ctx, "zabbix_maintenance", **params).hints == ["missing-object"]
    now = int(time.time())
    maint = {"maintenanceid": "3", "name": "win", "maintenance_type": "0", "active_since": str(now),
             "active_till": str(now + 7200), "hostgroups": [], "hosts": [{"host": "srl1"}],
             "timeperiods": [{"timeperiod_type": "0", "start_date": str(now), "period": "3600"}]}  # fmt: skip
    api.maintenances.append(maint)
    assert "data collection" in check(ctx, "zabbix_maintenance", **params).message
    maint["maintenance_type"] = "1"
    res = check(ctx, "zabbix_maintenance", **params)  # the time period ends after an hour
    assert res.status == "fail" and "7200 s" in res.message and res.observed["ends"] == now + 3600
    maint["timeperiods"][0]["period"] = "7200"
    res = check(ctx, "zabbix_maintenance", **params)  # right on paper, but Zabbix has nobody in it
    assert res.status == "fail" and res.hints == ["missing-object"]
    srl1.update(maintenance_status="1", maintenanceid="3")
    assert check(ctx, "zabbix_maintenance", **params).status == "pass"
    srl2.update(maintenance_status="1", maintenanceid="3")  # one host too many
    res = check(ctx, "zabbix_maintenance", **params)
    assert res.status == "fail" and res.observed == {"hosts": ["srl1", "srl2"]}
    maint["active_till"] = str(now + 86400)  # the last period still ends it on time
    srl2.update(maintenance_status="0")
    assert check(ctx, "zabbix_maintenance", **params).status == "pass"


def test_zabbix_unchanged_compares_with_the_baseline(zbx: tuple[Any, FakeZabbix]) -> None:
    ctx, api = zbx
    assert check(ctx, "zabbix_unchanged").hints == ["env-error"]  # no baseline
    api.add("srl1", "172.30.30.11")
    (ctx.run.baseline_dir / "zabbix.json").write_text(json.dumps(state.snapshot(api)))
    assert check(ctx, "zabbix_unchanged").status == "pass"
    api.add("stick-new", "172.30.30.12")
    res = check(ctx, "zabbix_unchanged")
    assert res.status == "fail" and res.observed == ["hosts: added stick-new"]
    assert check(ctx, "zabbix_unchanged", allow_new=["hosts:stick-new"]).status == "pass"


def test_start_saves_a_zabbix_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASK)
    api = FakeZabbix()
    api.add("frr1", "172.30.30.21")
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: None)
    monkeypatch.setattr(run, "run_script", lambda *a: None)
    monkeypatch.setattr(run, "rest_client", lambda name: api)
    info = run.start(task, tmp_path / "runs", FakeLab())  # type: ignore[arg-type]
    snap = json.loads((info.baseline_dir / "zabbix.json").read_text())
    assert snap["hosts"]["10800"]["label"] == "frr1"
    assert f'"Authorization: Bearer {TOKEN}"' in info.prompt and "/api_jsonrpc.php" in info.prompt
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, FakeLab())  # type: ignore[arg-type]
    assert env["STICK_ZABBIX_URL"] == "http://127.0.0.1:8085"
