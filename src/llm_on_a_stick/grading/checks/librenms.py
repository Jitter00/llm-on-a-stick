"""LibreNMS checks: devices as LibreNMS sees them after a poll the grader forces, alerts that really fired,
and nothing else changed."""

from __future__ import annotations

import json
from typing import Any

from llm_on_a_stick.grading import librenmsstate as state
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.checks.builtin import _dig, _plain
from llm_on_a_stick.grading.context import GradeContext, ServiceUnavailable

SAMPLE = 10


def _refresh(ctx: GradeContext, hostname: str | None = None) -> None:
    try:
        state.refresh(ctx.services.rest(state.SERVICE), hostname)
    except state.LibreNMSError as exc:
        raise ServiceUnavailable(str(exc)) from exc


def _device(ctx: GradeContext, hostname: str) -> dict[str, Any] | None:
    found = [d for d in state.devices(ctx.services.rest(state.SERVICE)) if d["hostname"] == hostname]
    return found[0] if found else None


@check("librenms_device")
def librenms_device(
    ctx: GradeContext, hostname: str, expect: dict[str, Any] | None = None, poll: bool = True
) -> Verdict:
    """LibreNMS monitors the device `hostname` (the name or address it was added with), and after a poll
    forced now (`poll: false` to skip it) its fields have the `expect` values, e.g. {status: 1, os: srlinux,
    community: ...}. `status: 1` means LibreNMS reached it over SNMP in that poll."""
    if _device(ctx, hostname) is None:
        return Verdict("fail", f"{hostname} is not in LibreNMS", expected=expect, hints=["missing-object"])
    if poll:
        _refresh(ctx, hostname)
    device = _device(ctx, hostname) or {}
    wrong = {k: got for k, want in (expect or {}).items() if (got := _dig(device, k)) != _plain(want)}
    if wrong:
        return Verdict(
            "fail", f"{hostname}: {len(wrong)} of {len(expect or {})} fields wrong",
            expected=expect, observed=wrong, hints=["wrong-config"],
        )  # fmt: skip
    return Verdict(
        "pass", f"{hostname}: monitored, {len(expect or {})} field(s) as expected", expected=expect
    )


@check("librenms_absent")
def librenms_absent(ctx: GradeContext, hostname: str) -> Verdict:
    """LibreNMS does not monitor the device `hostname`."""
    if _device(ctx, hostname) is None:
        return Verdict("pass", f"{hostname} is not in LibreNMS")
    return Verdict("fail", f"{hostname} is in LibreNMS and shouldn't be", hints=["collateral-change"])


@check("librenms_alert")
def librenms_alert(
    ctx: GradeContext,
    rule: str,
    devices: list[str],
    count: int | None = None,
    severity: str | None = None,
) -> Verdict:
    """One alert rule is named `rule` (with that `severity`, if given), and after a poll of every device,
    forced now, it has active alerts on exactly the `devices` (hostnames): `count` alerts in all (default:
    one per device). A rule that matches too much raises more alerts, one per port."""
    api = ctx.services.rest(state.SERVICE)
    rules = [r for r in state.listing(api, "rules", "rules") if r.get("name") == rule]
    if len(rules) != 1:
        return Verdict(
            "fail", f"{len(rules)} alert rule(s) named {rule!r}, expected exactly one",
            hints=["missing-object" if not rules else "wrong-config"],
        )  # fmt: skip
    if rules[0].get("disabled"):
        return Verdict("fail", f"alert rule {rule!r} is disabled", hints=["wrong-config"])
    if severity is not None and rules[0].get("severity") != severity:
        return Verdict(
            "fail", f"alert rule {rule!r} has the wrong severity",
            expected=severity, observed=rules[0].get("severity"), hints=["wrong-config"],
        )  # fmt: skip
    _refresh(ctx)
    names = {str(d["device_id"]): d["hostname"] for d in state.devices(api)}
    active = [
        a
        for a in state.listing(api, "alerts?state=1", "alerts")
        if str(a.get("rule_id")) == str(rules[0]["id"])
    ]
    on = sorted(names.get(str(a.get("device_id")), str(a.get("device_id"))) for a in active)
    want = count if count is not None else len(devices)
    expected = {"devices": sorted(devices), "count": want}
    if sorted(set(on)) == sorted(devices) and len(active) == want:
        return Verdict(
            "pass", f"rule {rule!r}: {len(active)} active alert(s), where expected", expected=expected
        )
    return Verdict(
        "fail", f"rule {rule!r}: {len(active)} active alert(s), not where expected",
        expected=expected, observed={"devices": on[:SAMPLE], "count": len(active)},
        hints=["missing-object" if not active else "wrong-config"],
    )  # fmt: skip


@check("librenms_unchanged")
def librenms_unchanged(
    ctx: GradeContext,
    allow_new: list[str] | None = None,
    allow_changed: list[str] | None = None,
    allow_deleted: list[str] | None = None,
) -> Verdict:
    """LibreNMS matches its state at `stick task start` (baseline/librenms.json), except what the lists
    allow: a kind (`devices`, `rules`, `groups`) or one object as `kind:label` (`devices:172.30.30.11`,
    `rules:my rule`). For a device, only how it is monitored counts (address, community, version, port,
    disabled), not what polling found. A device deleted and added again counts as deleted and added."""
    path = ctx.run.baseline_dir / f"{state.SERVICE}.json"
    if not path.exists():
        return Verdict(
            "error", "no LibreNMS baseline: the task must list librenms under requires.services",
            hints=["env-error"],
        )  # fmt: skip
    before: state.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "allow_new": allow_new or [],
        "allow_changed": allow_changed or [],
        "allow_deleted": allow_deleted or [],
    }
    problems = state.diff(before, state.snapshot(ctx.services.rest(state.SERVICE)), **allowed)
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected=allowed, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "nothing else changed in LibreNMS")
