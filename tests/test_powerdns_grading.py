"""Unit tests for the PowerDNS section: the service definition, the state and the checks.

No Docker and no DNS: the API and the resolver are fakes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import lab, paths, services
from llm_on_a_stick.grading import powerdnsstate as state
from llm_on_a_stick.grading import run
from llm_on_a_stick.services.spec import VolumesSnapshot
from llm_on_a_stick.tasks import load_task
from test_grading import FakeLab, check, make_ctx

TASK = paths.sections_dir() / "powerdns" / "powerdns-who-points-here"
Records = list[tuple[str, bool]]  # content, disabled


class FakePowerDNS:
    """The parts of /api/v1 the grader reads, and what the DNS port would answer for the same records."""

    def __init__(self) -> None:
        self.zones: dict[str, dict[tuple[str, str], tuple[int, Records]]] = {
            "stick.lab.": {
                ("stick.lab.", "SOA"): (3600, [("ns1.stick.lab. hostmaster.stick.lab. 1 1 1 1 1", False)]),
                ("web.stick.lab.", "A"): (900, [("198.19.7.10", False)]),
            }
        }

    def get(self, path: str) -> Any:
        if path == "servers/localhost/zones":
            return [{"name": z, "kind": "Native", "dnssec": False, "account": ""} for z in self.zones]
        zone = path.removeprefix("servers/localhost/zones/")
        rrsets = [
            {"name": n, "type": t, "ttl": ttl, "records": [{"content": c, "disabled": d} for c, d in recs]}
            for (n, t), (ttl, recs) in self.zones[zone].items()
        ]
        return {"name": zone, "rrsets": rrsets}

    def resolve(self, name: str, rtype: str) -> tuple[list[str], int | None]:
        for rrsets in self.zones.values():
            if (state.fqdn(name), rtype) in rrsets:
                ttl, records = rrsets[state.fqdn(name), rtype]
                values = sorted(c.lower() for c, disabled in records if not disabled)
                return (values, ttl) if values else ([], None)
        return [], None


class FakeServices:
    def __init__(self, api: FakePowerDNS) -> None:
        self.api = api

    def rest(self, name: str) -> FakePowerDNS:
        assert name == "powerdns"
        return self.api


@pytest.fixture
def dns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FakePowerDNS]:
    api = FakePowerDNS()
    ctx = make_ctx(tmp_path)
    ctx.services = FakeServices(api)  # type: ignore[assignment]
    monkeypatch.setattr(state, "resolve", api.resolve)
    (ctx.run.baseline_dir / "powerdns.json").write_text(json.dumps(state.snapshot(api)))
    return ctx, api


# --------------------------------------------------------------------------- the service


def test_powerdns_service_definition() -> None:
    spec = services.load("powerdns", env={})
    assert spec.project == "stick-powerdns"
    assert spec.health.url == "http://127.0.0.1:8090/api/v1/servers/localhost"
    assert spec.api_settings is not None
    assert spec.health.headers == {"X-API-Key": "stick-powerdns-key"} == spec.api_settings.headers
    assert isinstance(spec.snapshot, VolumesSnapshot) and spec.snapshot.volumes == ["powerdns-data"]
    assert spec.mcp is not None and len(spec.mcp.allow) == 6
    assert spec.mcp.env["POWERDNS_API_URL"] == "http://127.0.0.1:8090/api/v1"
    other = services.load("powerdns", lab.env({}, 1))
    assert other.mcp is not None and other.mcp.env["POWERDNS_API_URL"] == "http://127.0.0.1:8190/api/v1"


def test_the_dns_port_follows_the_lab_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    assert state.dns_port() == 8091
    monkeypatch.setenv("STICK_INSTANCE", "2")
    assert state.dns_port() == 8291


def test_the_api_description_in_the_image_is_the_one_the_entrypoint_names() -> None:
    image = paths.image_dir("mcp")
    assert (image / "powerdns-api.yaml").read_text(encoding="utf-8").startswith("openapi: 3.")
    assert "/opt/mcp/powerdns-api/powerdns-api.yaml" in (image / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (image / "stick-mcp-entrypoint.sh").read_text(encoding="utf-8")
    assert "--spec-path /opt/mcp/powerdns-api/powerdns-api.yaml" in entrypoint


# --------------------------------------------------------------------------- the checks


def test_dns_record_compares_the_whole_answer(dns: tuple[Any, FakePowerDNS]) -> None:
    ctx, api = dns
    one = {"name": "web.stick.lab", "values": ["198.19.7.10"]}
    assert check(ctx, "dns_record", **one, ttl=900).status == "pass"
    assert check(ctx, "dns_record", name="WEB.stick.lab.", values=["198.19.7.10"]).status == "pass"
    res = check(ctx, "dns_record", name="web.stick.lab", values=["198.19.7.10", "198.19.7.20"])
    assert res.hints == ["wrong-config"] and res.observed == {"values": ["198.19.7.10"], "ttl": 900}
    assert "TTL is 900" in check(ctx, "dns_record", **one, ttl=300).message
    assert check(ctx, "dns_record", name="db.stick.lab", values=["198.19.7.11"]).hints == ["missing-object"]
    assert check(ctx, "dns_record", name="db.stick.lab", values=[]).status == "pass"  # expected to be absent
    assert check(ctx, "dns_record", name="web.stick.lab", values=[]).hints == ["collateral-change"]

    api.zones["stick.lab."]["web.stick.lab.", "A"] = (900, [("198.19.7.10", True)])  # disabled: no answer
    assert check(ctx, "dns_record", **one).hints == ["missing-object"]


def test_dns_record_compares_names_without_case_or_the_last_dot(dns: tuple[Any, FakePowerDNS]) -> None:
    ctx, api = dns
    api.zones["7.19.198.in-addr.arpa."] = {
        ("10.7.19.198.in-addr.arpa.", "PTR"): (3600, [("web.stick.lab.", False)])
    }
    params = {"name": "10.7.19.198.in-addr.arpa", "type": "ptr"}
    assert check(ctx, "dns_record", **params, values=["Web.stick.lab"]).status == "pass"
    assert check(ctx, "dns_record", **params, values=["db.stick.lab."]).status == "fail"


def test_dns_record_reports_a_server_that_does_not_answer(
    dns: tuple[Any, FakePowerDNS], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = dns

    def down(name: str, rtype: str) -> Any:
        raise state.DnsError("no DNS answer from PowerDNS")

    monkeypatch.setattr(state, "resolve", down)
    res = check(ctx, "dns_record", name="web.stick.lab", values=["198.19.7.10"])
    assert res.status == "error" and res.hints == ["env-error"]


def test_powerdns_unchanged_sees_record_sets_and_zones(dns: tuple[Any, FakePowerDNS]) -> None:
    ctx, api = dns
    assert check(ctx, "powerdns_unchanged").status == "pass"
    zone = api.zones["stick.lab."]
    zone["stick.lab.", "SOA"] = (3600, [("ns1.stick.lab. hostmaster.stick.lab. 2 1 1 1 1", False)])
    assert check(ctx, "powerdns_unchanged").status == "pass"  # the serial moved: not compared

    zone["web.stick.lab.", "A"] = (900, [("198.19.7.20", False)])  # replaced instead of added to
    zone["db.stick.lab.", "A"] = (300, [("198.19.7.11", False)])
    api.zones["new.example."] = {}
    res = check(ctx, "powerdns_unchanged")
    assert res.observed == [
        "zones: added new.example.",
        "rrsets: changed web.stick.lab./A (records)",
        "rrsets: added db.stick.lab./A",
    ]
    allowed = check(
        ctx, "powerdns_unchanged",
        allow_changed=["rrsets:web.stick.lab./A"], allow_new=["rrsets:db.stick.lab./A", "zones"],
    )  # fmt: skip
    assert allowed.status == "pass"
    del zone["web.stick.lab.", "A"]
    res = check(ctx, "powerdns_unchanged", allow_new=["rrsets", "zones"])
    assert res.observed == ["rrsets: deleted web.stick.lab./A"]
    (ctx.run.baseline_dir / "powerdns.json").unlink()
    assert check(ctx, "powerdns_unchanged").hints == ["env-error"]


def test_a_disabled_record_is_a_change(dns: tuple[Any, FakePowerDNS]) -> None:
    ctx, api = dns
    api.zones["stick.lab."]["web.stick.lab.", "A"] = (900, [("198.19.7.10", True)])
    assert check(ctx, "powerdns_unchanged").observed == ["rrsets: changed web.stick.lab./A (records)"]


def test_start_saves_a_powerdns_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASK)
    api = FakePowerDNS()
    monkeypatch.setattr(run.lifecycle, "restore_snapshot", lambda spec: None)
    monkeypatch.setattr(run, "run_script", lambda *a: None)
    monkeypatch.setattr(run, "rest_client", lambda name: api)
    info = run.start(task, tmp_path / "runs", FakeLab())  # type: ignore[arg-type]
    snap = json.loads((info.baseline_dir / "powerdns.json").read_text())
    assert list(snap["zones"]) == ["stick.lab."] and list(snap["rrsets"]) == ["web.stick.lab./A"]
    env = run.script_env(task, info.run_dir, info.workspace, info.canaries, FakeLab())  # type: ignore[arg-type]
    assert env["STICK_POWERDNS_URL"] == "http://127.0.0.1:8090"
