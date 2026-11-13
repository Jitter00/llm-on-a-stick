"""Unit tests for the LibreNMS section: the service definition, the state snapshot and the checks.

No Docker: the API is a fake, and the `lnms` calls the checks make are recorded instead of run.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import paths, services
from llm_on_a_stick.grading import librenmsstate as state
from llm_on_a_stick.grading import run
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.seed import RestError
from llm_on_a_stick.services.spec import MysqlSnapshot
from llm_on_a_stick.tasks import load_task
from test_grading import FakeLab, check, make_ctx

TASK = paths.sections_dir() / "librenms" / "librenms-fix-monitoring"


class FakeLibreNMS:
    """The parts of /api/v0 the grader reads; a poll (`lnms device:poll`) turns pending devices up."""

    def __init__(self) -> None:
        self.devices: list[dict[str, Any]] = []
        self.rules: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.polled: list[str] = []

    def add(self, hostname: str, **fields: Any) -> dict[str, Any]:
        dev = {
            "device_id": len(self.devices) + 1, "hostname": hostname, "community": "stick-ro",
            "snmpver": "v2c",
            "port": 161, "transport": "udp", "disabled": 0, "ignore": 0, "snmp_disable": 0, "status": 1,
            "os": "linux", "last_discovered": "2026-11-09 10:00:00", "sysName": hostname, **fields,
        }  # fmt: skip
        self.devices.append(dev)
        return dev

    def get(self, path: str) -> Any:
        if path == "devices":
            return {"status": "ok", "devices": self.devices}
        if path == "rules":
            if not self.rules:
                raise RestError("GET rules -> HTTP 404: no rules")
            return {"status": "ok", "rules": self.rules}
        if path == "devicegroups":
            raise RestError("GET devicegroups -> HTTP 404: No device groups found")
        if path == "alerts?state=1":
            return {"status": "ok", "alerts": self.alerts}
        raise AssertionError(path)


class FakeServices:
    def __init__(self, api: FakeLibreNMS) -> None:
        self.api = api

    def rest(self, name: str) -> FakeLibreNMS:
        assert name == "librenms"
        return self.api


@pytest.fixture
def nms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FakeLibreNMS]:
    api = FakeLibreNMS()
    ctx = make_ctx(tmp_path)
    ctx.services = FakeServices(api)  # type: ignore[assignment]

    def lnms(*args: str, timeout_s: int = 300) -> subprocess.CompletedProcess[str]:
        api.polled.append(" ".join(args))
        if args[0] == "device:poll":
            for d in api.devices:
                if args[1] in ("all", d["hostname"]) and d.get("pending"):
                    d["status"] = 1
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(state, "lnms", lnms)
    return ctx, api


# --------------------------------------------------------------------------- the service


def test_librenms_service_definition() -> None:
    spec = services.load("librenms", env={})
    assert isinstance(spec.snapshot, MysqlSnapshot)
    assert spec.snapshot.path == "/snapshots/baseline.sql" and not spec.snapshot.stop
    assert spec.seed is None and spec.api_settings is not None
    assert spec.api_settings.base_url == "http://127.0.0.1:8084/api/v0/"
    assert spec.api_settings.headers["X-Auth-Token"] == spec.health.headers["X-Auth-Token"]
    assert spec.init is not None and spec.init.restart == ["librenms", "dispatcher"]
    assert any("user:add" in " ".join(s.cmd) for s in spec.init.steps)
    assert any("snmp.community" in s.cmd for s in spec.init.steps)  # no fallback to "public"
    assert services.load("librenms", env={"STICK_LIBRENMS_PORT": "9000"}).health.url.startswith(
        "http://127.0.0.1:9000/"
    )


def test_service_vars_give_the_librenms_token_without_a_scheme() -> None:
    values = run.service_vars()["librenms"]
    assert values["url"] == "http://127.0.0.1:8084"
    token = services.load("librenms").health.headers["X-Auth-Token"]
    assert values["token"] == token and "auth" not in values


def test_mysql_snapshot_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = services.load("librenms", env={})
    calls: list[list[str]] = []
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(lifecycle, "wait_healthy", lambda spec, timeout: None)
    lifecycle.take_snapshot(spec)
    lifecycle.restore_snapshot(spec)
    dump, restore, flush = [c for c in calls if "test" not in c]  # minus the has_snapshot probe
    assert "mariadb-dump" in dump[-1] and "MYSQL_PWD=stick-librenms-db" in dump and "db" in dump
    assert dump[-1].count("stick-librenms-db") == 0  # the password travels in the environment, not argv
    assert restore[-1].startswith('mariadb -u"$SNAP_USER"') and "< " in restore[-1]
    assert flush[-3:] == ["redis", "valkey-cli", "FLUSHALL"]
    assert not any("up" in c for c in calls)  # loaded into the running service: nothing restarted


def test_up_takes_the_first_mysql_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = services.load("librenms", env={})
    calls: list[list[str]] = []
    have_dump = False

    def fake_run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        probe = argv[-3:] == ["test", "-f", "/snapshots/baseline.sql"]
        return subprocess.CompletedProcess(argv, 1 if probe and not have_dump else 0, "", "")

    monkeypatch.setattr(lifecycle, "_run", fake_run)
    monkeypatch.setattr(lifecycle, "ensure_mgmt_network", lambda: False)
    monkeypatch.setattr(lifecycle, "wait_healthy", lambda spec, timeout: None)
    monkeypatch.setattr(lifecycle, "healthy", lambda spec, timeout=5: True)
    assert lifecycle.up(spec).snapshot_taken  # no dump file yet: the baseline isn't "always there"
    assert "mariadb-dump" in calls[-1][-1]
    have_dump = True
    assert not lifecycle.up(spec).snapshot_taken  # a later `up` keeps the baseline


def test_up_runs_init_once(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = services.load("librenms", env={})
    calls: list[list[str]] = []
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(lifecycle, "ensure_mgmt_network", lambda: False)
    monkeypatch.setattr(lifecycle, "wait_healthy", lambda spec, timeout: None)
    monkeypatch.setattr(lifecycle, "has_snapshot", lambda spec: True)
    monkeypatch.setattr(lifecycle, "healthy", lambda spec, timeout=5: False)  # first boot
    lifecycle.up(spec)
    assert any("user:add" in " ".join(c) for c in calls) and calls[-1][-3:] == [
        "restart",
        "librenms",
        "dispatcher",
    ]
    calls.clear()
    monkeypatch.setattr(lifecycle, "healthy", lambda spec, timeout=5: True)  # already set up
    lifecycle.up(spec)
    assert len(calls) == 1 and "up" in calls[0]


# --------------------------------------------------------------------------- snapshot and diff


def test_snapshot_keeps_how_a_device_is_monitored_not_what_polling_found() -> None:
    api = FakeLibreNMS()
    api.add("172.30.30.11", os="srlinux")
    api.rules.append(
        {"id": 3, "name": "r", "severity": "critical", "disabled": 0, "builder": {}, "extra": None}
    )
    before = state.snapshot(api)
    assert set(before) == {"devices", "rules", "groups"} and before["groups"] == {}
    assert before["devices"]["1"]["label"] == "172.30.30.11" and "os" not in before["devices"]["1"]
    api.devices[0]["status"] = 0  # polling found it down: not an edit
    assert state.diff(before, state.snapshot(api), [], [], []) == []
    api.devices[0]["community"] = "other"
    api.rules[0]["disabled"] = 1
    assert state.diff(before, state.snapshot(api), [], [], []) == [
        "devices: changed 172.30.30.11 (community)",
        "rules: changed r (disabled)",
    ]
    assert state.diff(before, state.snapshot(api), [], ["devices:172.30.30.11", "rules"], []) == []


def test_diff_sees_a_deleted_and_re_added_device() -> None:
    api = FakeLibreNMS()
    api.add("172.30.30.21")
    before = state.snapshot(api)
    api.devices.clear()
    api.add("172.30.30.21")  # a new device_id
    api.devices[0]["device_id"] = 9
    problems = state.diff(before, state.snapshot(api), ["devices"], [], [])
    assert problems == ["devices: deleted 172.30.30.21"]


# --------------------------------------------------------------------------- checks


def test_librenms_device_polls_then_compares(nms: tuple[Any, FakeLibreNMS]) -> None:
    ctx, api = nms
    res = check(ctx, "librenms_device", hostname="172.30.30.11", expect={"status": 1})
    assert res.status == "fail" and res.hints == ["missing-object"]
    api.add("172.30.30.11", status=0, pending=True, os="srlinux", community="stick-x")
    res = check(ctx, "librenms_device", hostname="172.30.30.11", expect={"status": 1, "os": "srlinux"})
    assert res.status == "pass" and api.polled == ["device:poll 172.30.30.11 -q"]
    res = check(ctx, "librenms_device", hostname="172.30.30.11", expect={"community": "stick-ro"})
    assert res.status == "fail" and res.observed == {"community": "stick-x"} and res.hints == ["wrong-config"]
    api.devices[0]["last_discovered"] = None
    check(ctx, "librenms_device", hostname="172.30.30.11")
    assert api.polled[-2:] == ["device:discover 172.30.30.11 -q", "device:poll 172.30.30.11 -q"]
    assert check(ctx, "librenms_absent", hostname="172.30.30.11").hints == ["collateral-change"]
    assert check(ctx, "librenms_absent", hostname="172.30.30.12").status == "pass"


def test_librenms_alert_wants_exactly_the_expected_alerts(nms: tuple[Any, FakeLibreNMS]) -> None:
    ctx, api = nms
    srl1 = api.add("172.30.30.11")
    srl2 = api.add("172.30.30.12")
    params = {"rule": "my rule", "devices": ["172.30.30.11"], "severity": "critical"}
    assert check(ctx, "librenms_alert", **params).hints == ["missing-object"]  # no such rule
    api.rules.append({"id": 5, "name": "my rule", "severity": "warning", "disabled": 0})
    res = check(ctx, "librenms_alert", **params)
    assert res.status == "fail" and "severity" in res.message
    api.rules[0]["severity"] = "critical"
    res = check(ctx, "librenms_alert", **params)
    assert res.status == "fail" and res.hints == ["missing-object"]  # the rule never fired
    assert api.polled[-1] == "device:poll all -q"
    api.alerts.append({"id": 1, "rule_id": 5, "device_id": srl1["device_id"], "state": 1})
    assert check(ctx, "librenms_alert", **params).status == "pass"
    api.alerts.append({"id": 2, "rule_id": 5, "device_id": srl2["device_id"], "state": 1})  # too much
    res = check(ctx, "librenms_alert", **params)
    assert res.status == "fail" and res.observed["count"] == 2 and res.hints == ["wrong-config"]
    api.rules.append({"id": 6, "name": "my rule", "severity": "critical", "disabled": 0})  # a duplicate
    assert "exactly one" in check(ctx, "librenms_alert", **params).message


def test_librenms_unchanged_compares_with_the_baseline(nms: tuple[Any, FakeLibreNMS]) -> None:
    ctx, api = nms
    assert check(ctx, "librenms_unchanged").hints == ["env-error"]  # no baseline
    api.add("172.30.30.11")
    (ctx.run.baseline_dir / "librenms.json").write_text(json.dumps(state.snapshot(api)))
    assert check(ctx, "librenms_unchanged").status == "pass"
    api.add("172.30.30.12")
    res = check(ctx, "librenms_unchanged")
    assert res.status == "fail" and res.observed == ["devices: added 172.30.30.12"]
    assert check(ctx, "librenms_unchanged", allow_new=["devices:172.30.30.12"]).status == "pass"


def test_start_saves_a_librenms_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASK)
    api = FakeLibreNMS()
    api.add("172.30.30.21")
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: None)
    monkeypatch.setattr(run, "run_script", lambda *a: None)
    monkeypatch.setattr(run, "rest_client", lambda name: api)
    info = run.start(task, tmp_path / "runs", FakeLab())  # type: ignore[arg-type]
    snap = json.loads((info.baseline_dir / "librenms.json").read_text())
    assert snap["devices"]["1"]["label"] == "172.30.30.21"
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, FakeLab())  # type: ignore[arg-type]
    assert env["STICK_LIBRENMS_URL"] == "http://127.0.0.1:8084" and "STICK_LIBRENMS_AUTH" not in env
