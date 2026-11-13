"""Nautobot grading without a Nautobot: nautobot_object, _unchanged and _graphql, and the baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import paths
from llm_on_a_stick.grading import run, sotstate
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.services.seed import RestError
from llm_on_a_stick.tasks import load_task
from test_grading import FakeLab, check, make_ctx
from test_netbox_grading import FakeNetBox

NAUTOBOT_TASK = paths.sections_dir() / "nautobot" / "nautobot-query-interface"
DEV = "0af0c0cf-93f0-4865-97d5-76f3517156ab"  # Nautobot ids are UUIDs


class FakeNautobot(FakeNetBox):
    """FakeNetBox plus what Nautobot adds: `depth` (recorded, not applied) and a GraphQL endpoint."""

    def __init__(self, data: dict[str, list[dict[str, Any]]], graphql: Any = None) -> None:
        super().__init__(data)
        self.paths: list[str] = []
        self.graphql = graphql
        self.queries: list[str] = []

    def get(self, path: str) -> Any:
        self.paths.append(path)
        endpoint, _, query = path.partition("/?")
        query = "&".join(p for p in query.split("&") if not p.startswith("depth="))
        return super().get(f"{endpoint}/?{query}")

    def post(self, path: str, body: Any) -> Any:
        assert path == "graphql/"
        self.queries.append(body["query"])
        if isinstance(self.graphql, Exception):
            raise self.graphql
        return self.graphql


class FakeServices:
    def __init__(self, nb: FakeNautobot) -> None:
        self.nb = nb

    def rest(self, name: str) -> FakeNautobot:
        assert name == "nautobot"
        return self.nb


def seeded() -> dict[str, list[dict[str, Any]]]:
    return {
        "extras/roles": [{"id": "r1", "name": "Leaf", "natural_slug": "leaf_r1", "notes_url": "u"}],
        "dcim/devices": [
            {
                "id": DEV, "name": "frr2", "role": {"id": "r1", "name": "Leaf"},
                "status": {"id": "s1", "name": "Active"}, "location": {"id": "l1", "name": "stick-lab"},
                "primary_ip4": {"id": "ip1", "address": "172.30.30.22/24"}, "last_updated": "t0",
            }
        ],
        "dcim/interfaces": [
            {"id": "i1", "name": "eth1", "device": {"id": DEV, "name": "frr2"}, "cable": None,
             "cable_peer": None, "ip_address_count": 0},
        ],
    }  # fmt: skip


def nb_ctx(tmp_path: Path, nb: FakeNautobot) -> GradeContext:
    ctx = make_ctx(tmp_path)
    ctx.services = FakeServices(nb)  # type: ignore[assignment]
    return ctx


# --------------------------------------------------------------------------- nautobot_object


def test_nautobot_object_expands_related_objects_one_level(tmp_path: Path) -> None:
    nb = FakeNautobot(seeded())
    ctx = nb_ctx(tmp_path, nb)
    expect = {"role.name": "Leaf", "status.name": "Active", "location.name": "stick-lab"}
    res = check(ctx, "nautobot_object", endpoint="dcim/devices", filters={"name": "frr2"}, expect=expect)
    assert res.status == "pass", res.message
    assert "depth=1" in nb.paths[-1]

    res = check(ctx, "nautobot_object", endpoint="dcim/devices", filters={"name": "frr2"},
                expect={"status.name": "Planned"})  # fmt: skip
    assert res.status == "fail" and res.observed == {"status.name": "Active"}
    assert "depth" not in res.message  # filters are reported as the task wrote them


def test_nautobot_object_depth_can_be_raised(tmp_path: Path) -> None:
    nb = FakeNautobot(seeded())
    ctx = nb_ctx(tmp_path, nb)
    check(ctx, "nautobot_object", endpoint="dcim/interfaces", filters={"name": "eth1", "depth": 2}, count=1)
    assert "depth=2" in nb.paths[-1] and "depth=1" not in nb.paths[-1]


def test_nautobot_object_filter_on_a_missing_device_means_no_match(tmp_path: Path) -> None:
    class Strict(FakeNautobot):
        def get(self, path: str) -> Any:
            raise RestError('GET x -> HTTP 400: {"device":["Select a valid choice. frr1 is not one of ..."]}')

    ctx = nb_ctx(tmp_path, Strict({}))
    res = check(ctx, "nautobot_object", endpoint="dcim/interfaces", filters={"device": "frr1"}, count=2)
    assert res.status == "fail" and res.observed == 0


# --------------------------------------------------------------------------- nautobot_unchanged


def baseline(ctx: GradeContext, nb: FakeNautobot) -> None:
    snap = sotstate.snapshot(nb, sotstate.ENDPOINTS["nautobot"])
    (ctx.run.baseline_dir / "nautobot.json").write_text(json.dumps(snap), encoding="utf-8")


def test_nautobot_unchanged_ignores_volatile_fields_and_cable_peers(tmp_path: Path) -> None:
    data = seeded()
    nb = FakeNautobot(data)
    ctx = nb_ctx(tmp_path, nb)
    baseline(ctx, nb)
    data["extras/roles"][0].update(natural_slug="other", notes_url="v")
    data["dcim/devices"][0]["last_updated"] = "t1"
    data["dcim/interfaces"][0].update(cable={"id": "c1"}, cable_peer={"id": "i9"}, ip_address_count=1)
    assert check(ctx, "nautobot_unchanged").status == "pass"


def test_nautobot_unchanged_catches_collateral_changes(tmp_path: Path) -> None:
    data = seeded()
    nb = FakeNautobot(data)
    ctx = nb_ctx(tmp_path, nb)
    baseline(ctx, nb)
    data["extras/roles"][0]["name"] = "Spine"
    data["ipam/ip-address-to-interface"] = [{"id": "m1", "ip_address": {"id": "ip9"}}]
    res = check(ctx, "nautobot_unchanged")
    assert res.status == "fail" and res.hints == ["collateral-change"]
    assert any("extras/roles: changed Leaf" in p for p in res.observed)
    res = check(ctx, "nautobot_unchanged", allow_new=["ipam/ip-address-to-interface"])
    assert len(res.observed) == 1


def test_nautobot_unchanged_without_baseline_is_an_env_error(tmp_path: Path) -> None:
    ctx = nb_ctx(tmp_path, FakeNautobot({}))
    res = check(ctx, "nautobot_unchanged")
    assert res.status == "error" and "nautobot" in res.message


# --------------------------------------------------------------------------- nautobot_graphql

REPLY = {"data": {"devices": [{"name": "d1", "interfaces": [{"name": "eth1", "ip_addresses": [
    {"address": "198.18.1.1/24"}]}, {"name": "eth0", "ip_addresses": []}]}]}}  # fmt: skip


def write_query(ctx: GradeContext, text: str = '{ devices(location: "x") { name } }') -> None:
    ctx.run.workspace.mkdir(parents=True, exist_ok=True)
    (ctx.run.workspace / "query.graphql").write_text(text, encoding="utf-8")


def test_nautobot_graphql_runs_the_saved_query(tmp_path: Path) -> None:
    nb = FakeNautobot({}, graphql=REPLY)
    ctx = nb_ctx(tmp_path, nb)
    write_query(ctx)
    res = check(ctx, "nautobot_graphql", path="query.graphql", must_contain=["d1", "198.18.1.1/24"],
                must_not_contain=["dx"])  # fmt: skip
    assert res.status == "pass", res.message
    assert nb.queries == ['{ devices(location: "x") { name } }']


def test_nautobot_graphql_missing_and_unwanted_values(tmp_path: Path) -> None:
    ctx = nb_ctx(tmp_path, FakeNautobot({}, graphql=REPLY))
    write_query(ctx)
    res = check(ctx, "nautobot_graphql", path="query.graphql", must_contain=["d2"], must_not_contain=["d1"])
    assert res.status == "fail" and res.observed == {"missing": ["d2"], "unwanted": ["d1"]}
    res = check(ctx, "nautobot_graphql", path="query.graphql", must_contain=["d1"], must_not_contain=["eth1"])
    assert res.status == "fail" and res.hints == ["unfiltered-output"]


def test_nautobot_graphql_errors_and_no_query(tmp_path: Path) -> None:
    errors = {"errors": [{"message": "Unknown argument 'site' on field 'Query.devices'."}]}
    ctx = nb_ctx(tmp_path, FakeNautobot({}, graphql=errors))
    assert check(ctx, "nautobot_graphql", path="query.graphql", must_contain=["d1"]).hints == ["no-output"]
    write_query(ctx)
    res = check(ctx, "nautobot_graphql", path="query.graphql", must_contain=["d1"])
    assert res.status == "fail" and res.hints == ["wrong-format"] and "site" in res.observed[0]

    ctx = nb_ctx(tmp_path / "syntax", FakeNautobot({}, graphql=RestError("POST x -> HTTP 400: Syntax Error")))
    write_query(ctx, "{ devices {")
    res = check(ctx, "nautobot_graphql", path="query.graphql", must_contain=["d1"])
    assert res.status == "fail" and "Syntax Error" in res.message


# --------------------------------------------------------------------------- task start


def test_service_vars_give_the_nautobot_token_header() -> None:
    nb = run.service_vars()["nautobot"]
    assert nb["url"].startswith("http://127.0.0.1:")
    assert nb["auth"] == f"Token {nb['token']}"


def test_start_resets_nautobot_and_saves_its_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = load_task(NAUTOBOT_TASK)
    events: list[str] = []
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: events.append(f"reset {spec.name}"))
    monkeypatch.setattr(run, "run_script", lambda task, script, kind, *_: events.append(kind))
    clients: list[str] = []

    def client(name: str) -> FakeNautobot:
        clients.append(name)
        return FakeNautobot(seeded())

    monkeypatch.setattr(run, "rest_client", client)
    info = run.start(task, tmp_path / "runs", FakeLab())  # type: ignore[arg-type]
    assert events == ["reset nautobot", "setup"] and clients == ["nautobot"]
    snap = json.loads((info.baseline_dir / "nautobot.json").read_text())
    assert snap["dcim/devices"][DEV]["name"] == "frr2"
    assert set(snap) == set(sotstate.ENDPOINTS["nautobot"])
    assert not (info.baseline_dir / "netbox.json").exists()
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, FakeLab())  # type: ignore[arg-type]
    assert env["STICK_NAUTOBOT_AUTH"].startswith("Token ")
