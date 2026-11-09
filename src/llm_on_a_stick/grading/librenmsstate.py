"""LibreNMS for grading: make it look at the devices now, a snapshot of what a task may touch, and what
changed since.

LibreNMS learns about devices by polling them, on its own schedule. The grader doesn't wait for that: it runs
the discovery and the poll itself (`lnms`, in the service's container), so a result never depends on timing.
A poll also evaluates the alert rules for the device.

`stick task start` saves the snapshot to baseline/librenms.json right after setup; the `librenms_unchanged`
check compares it with the service at grading time.
"""

from __future__ import annotations

import subprocess
from typing import Any, Protocol

from llm_on_a_stick import services
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.seed import RestError

SERVICE = "librenms"
CONTAINER = "librenms"  # the compose service that has `lnms`

# What a device is monitored with. Not here: what polling fills in (os, sysName, uptime, status...).
DEVICE_FIELDS = (
    "hostname",
    "community",
    "snmpver",
    "port",
    "transport",
    "disabled",
    "ignore",
    "snmp_disable",
)
RULE_FIELDS = ("name", "severity", "disabled", "builder", "extra")

Snapshot = dict[str, dict[str, dict[str, Any]]]  # kind (devices, rules, groups) -> id -> object


class LibreNMSError(RuntimeError):
    pass


class Api(Protocol):
    def get(self, path: str) -> Any: ...


def lnms(*args: str, timeout_s: int = 300) -> subprocess.CompletedProcess[str]:
    """Run `lnms <args>` in the LibreNMS container."""
    argv = lifecycle.compose_argv(services.load(SERVICE), "exec", "-T", CONTAINER, "lnms", *args)
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout_s)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise LibreNMSError(f"cannot run lnms {' '.join(args)}: {exc}") from exc


def listing(api: Api, path: str, key: str) -> list[dict[str, Any]]:
    """A list endpoint's objects. LibreNMS answers an empty list with HTTP 404 on some endpoints."""
    try:
        reply = api.get(path)
    except RestError as exc:
        if "HTTP 404" in str(exc):
            return []
        raise
    items = (reply or {}).get(key) or []
    return list(items)


def devices(api: Api) -> list[dict[str, Any]]:
    return listing(api, "devices", "devices")


def refresh(api: Api, hostname: str | None = None) -> None:
    """Have LibreNMS look at one device (or all) now: discovery where it never ran, then a poll."""
    targets = [d for d in devices(api) if hostname in (None, d["hostname"])]
    for device in targets:
        if not device.get("last_discovered"):
            lnms("device:discover", str(device["hostname"]), "-q")
    if targets:  # a device that doesn't answer makes the poll exit non-zero: that is a result, not an error
        lnms("device:poll", hostname or "all", "-q")


def snapshot(api: Api) -> Snapshot:
    return {
        "devices": {
            str(d["device_id"]): {"label": d["hostname"], **{k: d.get(k) for k in DEVICE_FIELDS}}
            for d in devices(api)
        },
        "rules": {
            str(r["id"]): {"label": r["name"], **{k: r.get(k) for k in RULE_FIELDS}}
            for r in listing(api, "rules", "rules")
        },
        "groups": {
            str(g["id"]): {"label": g["name"], "type": g.get("type"), "rules": g.get("rules")}
            for g in listing(api, "devicegroups", "groups")
        },
    }


def _allowed(kind: str, obj: dict[str, Any], allow: list[str]) -> bool:
    """`allow` entries are a kind ("rules": any of them) or kind:label ("devices:172.30.30.11")."""
    return kind in allow or f"{kind}:{obj.get('label')}" in allow


def diff(
    before: Snapshot,
    after: Snapshot,
    allow_new: list[str],
    allow_changed: list[str],
    allow_deleted: list[str],
) -> list[str]:
    """Changes from `before` to `after` that none of the allow lists covers. A device that was deleted and
    added again has a new id: it counts as deleted (its history is gone) and added."""
    problems: list[str] = []
    for kind, old in before.items():
        new = after.get(kind, {})
        for oid, obj in old.items():
            if oid not in new:
                if not _allowed(kind, obj, allow_deleted):
                    problems.append(f"{kind}: deleted {obj.get('label', oid)}")
            elif new[oid] != obj and not _allowed(kind, obj, allow_changed):
                fields = sorted(k for k in set(obj) | set(new[oid]) if obj.get(k) != new[oid].get(k))
                problems.append(f"{kind}: changed {obj.get('label', oid)} ({', '.join(fields)})")
        problems += [
            f"{kind}: added {obj.get('label', oid)}"
            for oid, obj in new.items()
            if oid not in old and not _allowed(kind, obj, allow_new)
        ]
    return problems
