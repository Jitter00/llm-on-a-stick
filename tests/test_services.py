from __future__ import annotations

from typing import Any

import yaml

from llm_on_a_stick import footprints, lab, paths, services
from llm_on_a_stick.services import lifecycle, seed
from llm_on_a_stick.services.spec import expand


def test_expand_defaults_and_overrides() -> None:
    assert expand("http://x:${PORT:-8081}/", {}) == "http://x:8081/"
    assert expand("http://x:${PORT:-8081}/", {"PORT": "9000"}) == "http://x:9000/"
    assert expand({"a": ["${A}"]}, {"A": "1"}) == {"a": ["1"]}
    assert expand("${UNSET}", {}) == ""


def test_netbox_is_available_and_valid() -> None:
    assert "netbox" in services.available()
    spec = services.load("netbox", env={})
    assert spec.project == "stick-netbox"
    assert spec.compose_file.is_file()
    assert spec.seed_file is not None
    assert spec.seed_file.is_file()
    assert spec.health.headers["Authorization"].startswith("Bearer nbt_stickadmin01.")


def test_every_service_has_a_footprint() -> None:
    fp = footprints.load()
    for name in services.available():
        assert name in fp.services, f"{name} missing from footprints.yaml"


def test_netbox_compose_matches_lab_network() -> None:
    compose = yaml.safe_load(services.load("netbox", env={}).compose_file.read_text(encoding="utf-8"))
    assert compose["networks"][lab.MGMT_NETWORK]["external"] is True
    ip = compose["services"]["netbox"]["networks"][lab.MGMT_NETWORK]["ipv4_address"]
    assert ip == lab.SERVICE_IPS["netbox"]


def test_lab_constants_match_topology() -> None:
    topo = yaml.safe_load(paths.topology_path("base").read_text(encoding="utf-8"))
    assert topo["mgmt"]["network"] == lab.MGMT_NETWORK
    assert topo["mgmt"]["ipv4-subnet"] == lab.MGMT_SUBNET


def test_service_ips_dont_collide_with_lab_nodes() -> None:
    topo = yaml.safe_load(paths.topology_path("base").read_text(encoding="utf-8"))
    node_ips = {n["mgmt-ipv4"] for n in topo["topology"]["nodes"].values()}
    assert not node_ips & set(lab.SERVICE_IPS.values())


def test_compose_argv() -> None:
    spec = services.load("netbox", env={})
    argv = lifecycle.compose_argv(spec, "up", "-d")
    assert argv[:4] == ["docker", "compose", "-p", "stick-netbox"]
    assert argv[-2:] == ["up", "-d"]


class FakeClient(seed.RestClient):
    def __init__(self, existing: dict[str, set[str]]) -> None:
        super().__init__("http://fake/api/", {})
        self.existing = existing
        self.posts: list[tuple[str, Any]] = []

    def request(self, method: str, path: str, body: Any = None) -> Any:
        endpoint, _, query = path.partition("/?")
        if method == "GET":
            value = query.split("=", 1)[1]
            return {"count": 1 if value in self.existing.get(endpoint, set()) else 0}
        self.posts.append((path, body))
        return {"id": len(self.posts)}


def test_seed_is_idempotent() -> None:
    spec = services.load("netbox", env={})
    assert spec.seed_file is not None
    entries = seed.load_entries(spec.seed_file)
    client = FakeClient(existing={"dcim/sites": {"stick-lab"}})
    result = seed.apply(client, entries)
    assert "dcim/sites/stick-lab" in result.existing
    assert len(result.created) == len(entries) - 1
    assert all(path.endswith("/") for path, _ in client.posts)


def test_seed_file_has_unique_lookups() -> None:
    spec = services.load("netbox", env={})
    assert spec.seed_file is not None
    keys = [(e.endpoint, e.data[e.lookup]) for e in seed.load_entries(spec.seed_file)]
    assert len(keys) == len(set(keys))
