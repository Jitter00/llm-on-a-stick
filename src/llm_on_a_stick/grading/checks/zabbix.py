"""Zabbix checks: hosts as Zabbix sees them after a poll the grader forces, problems a trigger really raised,
hosts really in maintenance, and nothing else changed."""

from __future__ import annotations

import json
import time
from typing import Any

from llm_on_a_stick.grading import zabbixstate as state
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext, ServiceUnavailable
from llm_on_a_stick.services.seed import RestError

SAMPLE = 10


def _api(ctx: GradeContext) -> state.Api:
    return ctx.services.rest(state.SERVICE)


def _host(ctx: GradeContext, ip: str) -> dict[str, Any] | None:
    found = [h for h in state.hosts(_api(ctx)) if h["ip"] == ip]
    return found[0] if found else None


def _matches(got: Any, want: Any) -> bool:
    """A list in `expect` means "contains all of these"; anything else is compared as text."""
    if isinstance(want, list):
        return isinstance(got, list) and all(str(w) in [str(g) for g in got] for w in want)
    return str(got) == str(want)


@check("zabbix_host")
def zabbix_host(
    ctx: GradeContext, ip: str, expect: dict[str, Any] | None = None, poll: bool = True, wait_s: int = 45
) -> Verdict:
    """Zabbix has a host whose SNMP interface is at `ip`, and after a poll forced now (`poll: false` to skip
    it) it has the `expect` values: any of host, name, status (0 = monitored), community (macros resolved),
    snmp_version, available (1 = Zabbix reached it over SNMP), groups and templates (lists: the host has at
    least these). The check waits up to `wait_s` seconds for `available` to become what is expected."""
    expect = expect or {}
    try:
        host = _host(ctx, ip)
        if host is None:
            return Verdict(
                "fail", f"no host with an SNMP interface at {ip} in Zabbix",
                expected=expect, hints=["missing-object"],
            )  # fmt: skip
        if poll:
            state.refresh(_api(ctx), [host["hostid"]])
        if "available" in expect:

            def reached() -> bool:
                now = _host(ctx, ip)
                return now is not None and _matches(now["available"], expect["available"])

            state.wait_for(reached, wait_s if poll else 0)
        host = _host(ctx, ip) or {}
    except (state.ZabbixError, RestError) as exc:
        raise ServiceUnavailable(str(exc)) from exc
    wrong = {k: host.get(k) for k, want in expect.items() if not _matches(host.get(k), want)}
    if wrong:
        if "available" in wrong and host.get("error"):
            wrong["error"] = host["error"]
        return Verdict(
            "fail", f"{ip}: {len([k for k in wrong if k != 'error'])} of {len(expect)} fields wrong",
            expected=expect, observed=wrong, hints=["wrong-config"],
        )  # fmt: skip
    return Verdict("pass", f"{ip}: in Zabbix, {len(expect)} field(s) as expected", expected=expect)


@check("zabbix_absent")
def zabbix_absent(ctx: GradeContext, ip: str) -> Verdict:
    """Zabbix has no host with an SNMP interface at `ip`."""
    try:
        host = _host(ctx, ip)
    except (state.ZabbixError, RestError) as exc:
        raise ServiceUnavailable(str(exc)) from exc
    if host is None:
        return Verdict("pass", f"{ip} is not in Zabbix")
    return Verdict("fail", f"{ip} is in Zabbix and shouldn't be", hints=["collateral-change"])


@check("zabbix_problem")
def zabbix_problem(
    ctx: GradeContext,
    trigger: str,
    hosts: list[str],
    severity: int | None = None,
    wait_s: int = 40,
) -> Verdict:
    """Exactly one trigger people made is named `trigger` (with that `severity`, 0-5, if given; 4 = High),
    it is enabled, it is on exactly the `hosts` (host names), and after a poll of its items, forced now, it
    is in problem state: one open problem. The check waits up to `wait_s` seconds for the problem."""
    api = _api(ctx)
    try:
        found = state.triggers(api, trigger)
        if len(found) != 1:
            return Verdict(
                "fail", f"{len(found)} trigger(s) named {trigger!r}, expected exactly one",
                observed=[{"hosts": sorted(h["host"] for h in t.get("hosts") or [])} for t in found][:SAMPLE],
                hints=["missing-object" if not found else "wrong-config"],
            )  # fmt: skip
        trig = found[0]
        on = sorted(h["host"] for h in trig.get("hosts") or [])
        observed = {"hosts": on, "severity": int(trig["priority"]), "expression": trig.get("expression")}
        expected = {"hosts": sorted(hosts), "severity": severity, "problems": 1}
        if str(trig.get("status")) != "0":
            return Verdict("fail", f"trigger {trigger!r} is disabled", hints=["wrong-config"])
        if severity is not None and int(trig["priority"]) != severity:
            return Verdict(
                "fail", f"trigger {trigger!r} has the wrong severity",
                expected=expected, observed=observed, hints=["wrong-config"],
            )  # fmt: skip
        if on != sorted(hosts):
            return Verdict(
                "fail", f"trigger {trigger!r} is not on the expected host",
                expected=expected, observed=observed, hints=["wrong-config"],
            )  # fmt: skip
        items = state.rpc(api, "item.get", {"triggerids": [trig["triggerid"]], "output": ["itemid"]})
        state.poll_now(api, [i["itemid"] for i in items])

        def problems() -> list[dict[str, Any]]:
            return list(
                state.rpc(api, "problem.get", {"objectids": [trig["triggerid"]], "output": ["eventid"]})
            )

        state.wait_for(lambda: len(problems()) >= 1, wait_s)
        count = len(problems())
    except (state.ZabbixError, RestError) as exc:
        raise ServiceUnavailable(str(exc)) from exc
    if count == 1:
        return Verdict(
            "pass", f"trigger {trigger!r}: on {', '.join(on)}, in problem state", expected=expected
        )
    return Verdict(
        "fail", f"trigger {trigger!r}: {count} open problem(s), expected 1",
        expected=expected, observed={**observed, "problems": count},
        hints=["wrong-config"],
    )  # fmt: skip


@check("zabbix_maintenance")
def zabbix_maintenance(
    ctx: GradeContext,
    name: str,
    hosts: list[str],
    duration_s: int,
    data_collection: bool = False,
    tolerance_s: int = 300,
    wait_s: int = 100,
) -> Verdict:
    """Exactly one maintenance is named `name`; it is with or without `data_collection`; it ends
    `duration_s` after the moment it was made (somewhere between the start of the run and now, give or take
    `tolerance_s`); and Zabbix really has exactly the `hosts` (host names) in it now. Zabbix works that out
    once a minute, so the check waits up to `wait_s` seconds."""
    api = _api(ctx)
    want_type = 0 if data_collection else 1
    expected = {"hosts": sorted(hosts), "data_collection": data_collection, "duration_s": duration_s}
    try:
        found = [m for m in state.maintenances(api) if m["name"] == name]
        if len(found) != 1:
            return Verdict(
                "fail", f"{len(found)} maintenance(s) named {name!r}, expected exactly one",
                expected=expected, hints=["missing-object" if not found else "wrong-config"],
            )  # fmt: skip
        maint = found[0]
        if int(maint["maintenance_type"]) != want_type:
            return Verdict(
                "fail",
                f"maintenance {name!r} is {'with' if want_type else 'without'} data collection",
                expected=expected, hints=["wrong-config"],
            )  # fmt: skip
        # It ends when the last time period does, or at active_till if that comes first.
        periods = [int(p["start_date"]) + int(p["period"]) for p in maint.get("timeperiods") or []
                   if str(p.get("timeperiod_type", "0")) == "0"]  # fmt: skip
        ends = min(int(maint["active_till"]), max(periods)) if periods else int(maint["active_till"])
        earliest = int(ctx.run.started_at.timestamp()) + duration_s - tolerance_s
        latest = int(time.time()) + duration_s + tolerance_s
        if not earliest <= ends <= latest:
            return Verdict(
                "fail", f"maintenance {name!r} doesn't end {duration_s} s after it was made",
                expected={**expected, "ends_between": [earliest, latest]},
                observed={"ends": ends, "active_since": maint["active_since"],
                          "active_till": maint["active_till"], "timeperiods": maint.get("timeperiods")},
                hints=["wrong-config"],
            )  # fmt: skip

        def inside() -> list[str]:
            return sorted(
                h["host"]
                for h in state.hosts(api)
                if h["maintenance"] == 1 and h["maintenanceid"] == str(maint["maintenanceid"])
            )

        state.reload_config()
        state.wait_for(lambda: inside() == sorted(hosts), wait_s, every_s=3)
        now_in = inside()
    except (state.ZabbixError, RestError) as exc:
        raise ServiceUnavailable(str(exc)) from exc
    if now_in == sorted(hosts):
        return Verdict(
            "pass", f"maintenance {name!r}: {len(now_in)} host(s) in it, as expected", expected=expected
        )
    return Verdict(
        "fail", f"maintenance {name!r}: {len(now_in)} host(s) in it now, not the expected ones",
        expected=expected, observed={"hosts": now_in[:SAMPLE]},
        hints=["missing-object" if not now_in else "wrong-config"],
    )  # fmt: skip


@check("zabbix_unchanged")
def zabbix_unchanged(
    ctx: GradeContext,
    allow_new: list[str] | None = None,
    allow_changed: list[str] | None = None,
    allow_deleted: list[str] | None = None,
) -> Verdict:
    """Zabbix matches its state at `stick task start` (baseline/zabbix.json), except what the lists allow: a
    kind (`hosts`, `triggers`, `maintenances`, `groups`, `macros`) or one object as `kind:label`
    (`hosts:srl1` by host name, `triggers:my trigger`, `maintenances:my window`). For a host, only how it is
    monitored counts (interfaces, community, macros, groups, templates, tags, enabled), not what polling
    found. A host deleted and added again counts as deleted and added."""
    path = ctx.run.baseline_dir / f"{state.SERVICE}.json"
    if not path.exists():
        return Verdict(
            "error", "no Zabbix baseline: the task must list zabbix under requires.services",
            hints=["env-error"],
        )  # fmt: skip
    before: state.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "allow_new": allow_new or [],
        "allow_changed": allow_changed or [],
        "allow_deleted": allow_deleted or [],
    }
    try:
        after = state.snapshot(_api(ctx))
    except (state.ZabbixError, RestError) as exc:
        raise ServiceUnavailable(str(exc)) from exc
    problems = state.diff(before, json.loads(json.dumps(after)), **allowed)
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected=allowed, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "nothing else changed in Zabbix")
