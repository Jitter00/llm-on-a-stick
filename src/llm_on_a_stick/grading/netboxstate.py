"""NetBox state for grading: a snapshot of the objects a task may touch, and what changed since.

`stick task start` saves the snapshot to baseline/netbox.json right after setup; the `netbox_unchanged` check
compares it with NetBox at grading time, so edits the task didn't ask for (a renamed role, a deleted device
type, an extra IP address) are caught even when the requested objects are right.
"""

from __future__ import annotations

from typing import Any, Protocol

# Objects a NetBox task is likely to touch: the seed (sites, roles, ...) and what setups create.
ENDPOINTS = (
    "dcim/sites",
    "dcim/manufacturers",
    "dcim/device-roles",
    "dcim/platforms",
    "dcim/device-types",
    "dcim/devices",
    "dcim/interfaces",
    "ipam/ip-addresses",
    "ipam/prefixes",
    "dcim/cables",
)
# Fields that change without anyone editing the object.
_VOLATILE = {"last_updated", "created", "url", "display", "display_url"}
# Fields of an interface that a new cable sets on both ends. The cable itself is tracked (dcim/cables), so
# ignoring them here doesn't hide anything.
_CABLE_DERIVED = {
    "cable", "cable_end", "link_peers", "link_peers_type", "_occupied",
    "connected_endpoints", "connected_endpoints_type", "connected_endpoints_reachable",
}  # fmt: skip

Snapshot = dict[str, dict[str, dict[str, Any]]]  # endpoint -> object id -> object


class Getter(Protocol):
    def get(self, path: str) -> Any: ...


def _stable(obj: dict[str, Any]) -> dict[str, Any]:
    # Counters (device_count, interface_count...) go up when a related object is added: not an edit.
    return {
        k: v
        for k, v in obj.items()
        if k not in _VOLATILE and k not in _CABLE_DERIVED and not k.endswith("_count")
    }


def snapshot(client: Getter, endpoints: tuple[str, ...] = ENDPOINTS) -> Snapshot:
    snap: Snapshot = {}
    for endpoint in endpoints:
        objects: dict[str, dict[str, Any]] = {}
        path: str | None = f"{endpoint}/?limit=1000"
        while path:
            page = client.get(path)
            for obj in page.get("results", []):
                objects[str(obj["id"])] = _stable(obj)
            nxt = page.get("next")
            path = nxt.split("/api/", 1)[1] if nxt and "/api/" in nxt else None
        snap[endpoint] = objects
    return snap


def _label(obj: dict[str, Any]) -> str:
    for key in ("name", "address", "prefix", "model", "slug"):
        if obj.get(key):
            return str(obj[key])
    return f"id {obj.get('id')}"


def diff(before: Snapshot, after: Snapshot, allow_new: list[str]) -> list[str]:
    """Changes from `before` to `after`, except new objects on the `allow_new` endpoints."""
    problems: list[str] = []
    for endpoint, old in before.items():
        new = after.get(endpoint, {})
        for oid, obj in old.items():
            if oid not in new:
                problems.append(f"{endpoint}: deleted {_label(obj)}")
            elif new[oid] != obj:
                fields = sorted(k for k in set(obj) | set(new[oid]) if obj.get(k) != new[oid].get(k))
                problems.append(f"{endpoint}: changed {_label(obj)} ({', '.join(fields)})")
        if endpoint not in allow_new:
            problems += [f"{endpoint}: added {_label(o)}" for oid, o in new.items() if oid not in old]
    return problems
