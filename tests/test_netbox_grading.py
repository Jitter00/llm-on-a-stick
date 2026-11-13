"""NetBox grading without a NetBox: netbox_object `expect`, netbox_unchanged, the baseline and the reset."""

from __future__ import annotations

import copy
import json
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import paths
from llm_on_a_stick.grading import run, sotstate
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.services.seed import RestError
from llm_on_a_stick.tasks import load_task
from test_grading import FakeLab, check, make_ctx

NETBOX_TASK = paths.sections_dir() / "netbox" / "netbox-drift"


class FakeNetBox:
    """GET <endpoint>/?<filters>: exact matches on top-level fields (or `field.name` for nested objects)."""

    def __init__(self, data: dict[str, list[dict[str, Any]]], page_size: int = 1000) -> None:
        self.data = data
        self.page_size = page_size

    def get(self, path: str) -> Any:
        endpoint, _, query = path.partition("/?")
        params = dict(urllib.parse.parse_qsl(query))
        offset = int(params.pop("offset", 0))
        params.pop("limit", None)

        def matches(obj: dict[str, Any]) -> bool:
            for key, want in params.items():
                got = obj.get(key)
                got = got.get("name") if isinstance(got, dict) else got
                if str(got) != want:
                    return False
            return True

        found = [o for o in self.data.get(endpoint.strip("/"), []) if matches(o)]
        page = found[offset : offset + self.page_size]
        more = offset + self.page_size < len(found)
        nxt = (
            f"http://nb/api/{endpoint}/?limit={self.page_size}&offset={offset + self.page_size}"
            if more
            else None
        )
        return {"count": len(found), "next": nxt, "results": copy.deepcopy(page)}


class FakeServices:
    def __init__(self, nb: FakeNetBox) -> None:
        self.nb = nb

    def rest(self, name: str) -> FakeNetBox:
        return self.nb

    def netbox(self) -> FakeNetBox:
        return self.nb


def seeded() -> dict[str, list[dict[str, Any]]]:
    return {
        "dcim/device-roles": [{"id": 1, "name": "Leaf", "slug": "leaf", "device_count": 0}],
        "dcim/devices": [
            {
                "id": 7, "name": "frr2", "role": {"id": 1, "slug": "leaf"},
                "status": {"value": "active", "label": "Active"},
                "primary_ip4": {"id": 3, "address": "172.30.30.22/24"}, "last_updated": "t0",
            }
        ],
        "ipam/ip-addresses": [{"id": 3, "address": "172.30.30.22/24", "assigned_object": {"name": "eth0"}}],
    }  # fmt: skip


def nb_ctx(tmp_path: Path, data: dict[str, list[dict[str, Any]]]) -> tuple[GradeContext, FakeNetBox]:
    ctx = make_ctx(tmp_path)
    nb = FakeNetBox(data)
    ctx.services = FakeServices(nb)  # type: ignore[assignment]
    return ctx, nb


# --------------------------------------------------------------------------- netbox_object expect


def test_netbox_object_expect_fields(tmp_path: Path) -> None:
    ctx, _ = nb_ctx(tmp_path, seeded())
    good = {"role.slug": "leaf", "status": "active", "primary_ip4.address": "172.30.30.22/24"}
    res = check(ctx, "netbox_object", endpoint="dcim/devices", filters={"name": "frr2"}, expect=good)
    assert res.status == "pass", res.message

    res = check(ctx, "netbox_object", endpoint="dcim/devices", filters={"name": "frr2"},
                expect={"role.slug": "spine", "platform.slug": "frr"})  # fmt: skip
    assert res.status == "fail" and res.hints == ["wrong-config"]
    assert res.observed == {"role.slug": "leaf", "platform.slug": None}


def test_netbox_object_expect_needs_exactly_one_match(tmp_path: Path) -> None:
    data = seeded()
    ctx, _ = nb_ctx(tmp_path, data)
    res = check(
        ctx, "netbox_object", endpoint="dcim/devices", filters={"name": "nope"}, expect={"name": "nope"}
    )
    assert res.status == "fail" and res.hints == ["missing-object"]
    data["dcim/devices"].append({**data["dcim/devices"][0], "id": 8})
    res = check(
        ctx, "netbox_object", endpoint="dcim/devices", filters={"name": "frr2"}, expect={"name": "frr2"}
    )
    assert res.status == "fail" and res.hints == ["wrong-config"]
    # Without `expect`, counting works as before.
    assert (
        check(ctx, "netbox_object", endpoint="dcim/devices", filters={"name": "frr2"}, count=2).status
        == "pass"
    )


# --------------------------------------------------------------------------- netbox_unchanged


def baseline(ctx: GradeContext, nb: FakeNetBox) -> None:
    snap = sotstate.snapshot(nb, ("dcim/device-roles", "dcim/devices", "ipam/ip-addresses"))
    (ctx.run.baseline_dir / "netbox.json").write_text(json.dumps(snap))


def test_netbox_unchanged_passes_when_only_counters_and_timestamps_move(tmp_path: Path) -> None:
    ctx, nb = nb_ctx(tmp_path, seeded())
    baseline(ctx, nb)
    nb.data["dcim/device-roles"][0]["device_count"] = 1
    nb.data["dcim/devices"][0]["last_updated"] = "t1"
    assert check(ctx, "netbox_unchanged").status == "pass"


@pytest.mark.parametrize(
    ("change", "allow_new", "status"),
    [
        (lambda d: d["dcim/device-roles"][0].update(slug="spine"), [], "fail"),  # edited a seed object
        (lambda d: d["dcim/devices"].clear(), ["dcim/devices"], "fail"),  # deleted one
        (lambda d: d["dcim/devices"].append({"id": 9, "name": "new"}), [], "fail"),  # added where not allowed
        (lambda d: d["dcim/devices"].append({"id": 9, "name": "new"}), ["dcim/devices"], "pass"),
    ],
)
def test_netbox_unchanged_catches_collateral_changes(
    tmp_path: Path, change: Any, allow_new: list[str], status: str
) -> None:
    ctx, nb = nb_ctx(tmp_path, seeded())
    baseline(ctx, nb)
    change(nb.data)
    res = check(ctx, "netbox_unchanged", allow_new=allow_new)
    assert res.status == status, res.observed
    if status == "fail":
        assert res.hints == ["collateral-change"]


def test_netbox_unchanged_without_baseline_is_an_env_error(tmp_path: Path) -> None:
    ctx, _ = nb_ctx(tmp_path, seeded())
    res = check(ctx, "netbox_unchanged")
    assert res.status == "error" and res.hints == ["env-error"]


def test_snapshot_follows_pages() -> None:
    nb = FakeNetBox({"dcim/devices": [{"id": i, "name": f"d{i}"} for i in range(5)]}, page_size=2)
    assert sorted(sotstate.snapshot(nb, ("dcim/devices",))["dcim/devices"]) == ["0", "1", "2", "3", "4"]


# --------------------------------------------------------------------------- task start


def test_service_vars_give_the_netbox_token_and_auth_header() -> None:
    nb = run.service_vars()["netbox"]
    assert nb["url"].startswith("http://127.0.0.1:")
    assert nb["auth"] == f"Bearer {nb['token']}" and nb["token"].startswith("nbt_")
    assert "token" not in run.service_vars()["oxidized"]


def test_start_resets_netbox_before_setup_and_saves_a_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = load_task(NETBOX_TASK)
    events: list[str] = []
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: events.append(f"reset {spec.name}"))
    monkeypatch.setattr(run, "run_script", lambda task, script, kind, *_: events.append(kind))
    monkeypatch.setattr(run, "rest_client", lambda name: FakeNetBox(seeded()))
    info = run.start(task, tmp_path / "runs", FakeLab())  # type: ignore[arg-type]
    assert events == ["reset netbox", "setup"]
    snap = json.loads((info.baseline_dir / "netbox.json").read_text())
    assert snap["dcim/devices"]["7"]["name"] == "frr2"
    assert "Authorization: Bearer nbt_" in info.prompt and "127.0.0.1" in info.prompt
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, FakeLab())  # type: ignore[arg-type]
    assert env["STICK_NETBOX_AUTH"].startswith("Bearer nbt_") and env["STICK_NETBOX_URL"].startswith("http")


def test_start_explains_a_netbox_that_is_not_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(spec: Any) -> None:
        raise run.ServiceError("no snapshot yet")

    monkeypatch.setattr(run.lifecycle, "restore_snapshot", down)
    with pytest.raises(run.RunError, match="stick svc up netbox"):
        run.start(load_task(NETBOX_TASK), tmp_path / "runs", FakeLab())  # type: ignore[arg-type]


def test_netbox_object_filter_on_a_missing_device_means_no_match(tmp_path: Path) -> None:
    class Strict(FakeNetBox):
        def get(self, path: str) -> Any:
            if "device=frr2" in path:
                raise RestError(
                    'GET x -> HTTP 400: {"device":["Select a valid choice. frr2 is not one of ..."]}'
                )
            return super().get(path)

    ctx = make_ctx(tmp_path)
    ctx.services = FakeServices(Strict({}))  # type: ignore[assignment]
    res = check(ctx, "netbox_object", endpoint="dcim/interfaces", filters={"device": "frr2"}, count=4)
    assert res.status == "fail" and res.hints == ["missing-object"]
    res = check(ctx, "netbox_object", endpoint="dcim/interfaces", filters={"device": "frr2"}, expect={"a": 1})
    assert res.status == "fail" and res.hints == ["missing-object"]


# --------------------------------------------------------------------------- cables


def cabled() -> dict[str, list[dict[str, Any]]]:
    return {
        "dcim/interfaces": [
            {"id": 1, "name": "ethernet-1/1", "device": {"name": "srl1"}, "cable": None, "link_peers": [],
             "_occupied": False, "description": ""},
            {"id": 2, "name": "eth1", "device": {"name": "n1"}, "cable": None, "link_peers": [],
             "_occupied": False, "description": ""},
        ],
        "dcim/cables": [],
    }  # fmt: skip


def connect(data: dict[str, list[dict[str, Any]]]) -> None:
    """What NetBox does when a cable is added between interfaces 1 and 2."""
    a, b = data["dcim/interfaces"]
    data["dcim/cables"].append(
        {"id": 5, "a_terminations": [{"object_id": 1}], "b_terminations": [{"object_id": 2}]}
    )
    for one, other in ((a, b), (b, a)):
        one.update(
            cable={"id": 5}, _occupied=True, link_peers=[{"name": other["name"], "device": other["device"]}]
        )


def test_netbox_object_expect_reads_list_items(tmp_path: Path) -> None:
    data = cabled()
    connect(data)
    ctx, _ = nb_ctx(tmp_path, data)
    filters = {"device": "srl1", "name": "ethernet-1/1"}
    good = {"link_peers.0.device.name": "n1", "link_peers.0.name": "eth1"}
    assert (
        check(ctx, "netbox_object", endpoint="dcim/interfaces", filters=filters, expect=good).status == "pass"
    )
    res = check(ctx, "netbox_object", endpoint="dcim/interfaces", filters=filters,
                expect={"link_peers.1.name": "eth1"})  # fmt: skip
    assert res.status == "fail" and res.observed == {"link_peers.1.name": None}


def test_netbox_unchanged_allows_a_cable_only_where_allowed(tmp_path: Path) -> None:
    ctx, nb = nb_ctx(tmp_path, cabled())
    snap = sotstate.snapshot(nb, ("dcim/interfaces", "dcim/cables"))
    (ctx.run.baseline_dir / "netbox.json").write_text(json.dumps(snap))
    connect(nb.data)
    # The interfaces' cable fields changed on both ends: that's the cable, not an edit.
    assert check(ctx, "netbox_unchanged", allow_new=["dcim/cables"]).status == "pass"
    res = check(ctx, "netbox_unchanged", allow_new=[])
    assert res.status == "fail" and res.observed == ["dcim/cables: added id 5"]
    nb.data["dcim/interfaces"][0]["description"] = "edited"
    res = check(ctx, "netbox_unchanged", allow_new=["dcim/cables"])
    assert res.status == "fail" and "changed ethernet-1/1 (description)" in res.observed[0]


def test_netbox_unchanged_ignores_ip_counters_on_interfaces(tmp_path: Path) -> None:
    data = cabled()
    data["dcim/interfaces"][0]["count_ipaddresses"] = 0
    ctx, nb = nb_ctx(tmp_path, data)
    snap = sotstate.snapshot(nb, ("dcim/interfaces",))
    (ctx.run.baseline_dir / "netbox.json").write_text(json.dumps(snap))
    nb.data["dcim/interfaces"][0]["count_ipaddresses"] = 1  # an IP was assigned to it: not an edit
    assert check(ctx, "netbox_unchanged").status == "pass"


def test_net24_canary_is_a_24_outside_the_ipv4_canaries() -> None:
    from llm_on_a_stick.grading import canaries

    values = canaries.generate({"pool": "net24", "addr": "ipv4"}, seed=3)
    octets = values["pool"].split(".")
    assert len(octets) == 3 and octets[:2] == ["198", "19"] and 0 <= int(octets[2]) <= 255
    assert values["addr"].startswith("198.18.")
