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


def test_nautobot_is_available_and_valid() -> None:
    assert "nautobot" in services.available()
    spec = services.load("nautobot", env={})
    assert spec.project == "stick-nautobot"
    assert spec.compose_file.is_file()
    assert spec.seed_file is not None
    assert spec.seed_file.is_file()
    assert spec.seed is not None
    assert spec.seed.kind == "rest"
    assert spec.health.headers["Authorization"].startswith("Token ")  # not NetBox 4's "Bearer nbt_..."


def test_every_service_has_a_footprint() -> None:
    fp = footprints.load()
    for name in services.available():
        assert name in fp.services, f"{name} missing from footprints.yaml"


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


def test_seed_files_have_unique_lookups() -> None:
    for name in ("netbox", "nautobot"):
        spec = services.load(name, env={})
        assert spec.seed_file is not None
        keys = [(e.endpoint, e.data[e.lookup]) for e in seed.load_entries(spec.seed_file)]
        assert len(keys) == len(set(keys)), name


def test_nautobot_seed_creates_what_it_refers_to_first() -> None:
    """Nautobot resolves {name: ...} references when the object is created, so the seed must be ordered."""
    spec = services.load("nautobot", env={})
    assert spec.seed_file is not None
    order = [e.endpoint for e in seed.load_entries(spec.seed_file)]
    assert order.index("dcim/location-types") < order.index("dcim/locations")
    assert order.index("dcim/manufacturers") < order.index("dcim/platforms")
    assert order.index("dcim/manufacturers") < order.index("dcim/device-types")
    assert order.index("ipam/namespaces") < order.index("ipam/prefixes")


# --------------------------------------------------------------------------- all services


def test_every_service_joins_the_lab_network_at_its_fixed_ip() -> None:
    for name in services.available():
        compose = yaml.safe_load(services.load(name, env={}).compose_file.read_text(encoding="utf-8"))
        assert compose["networks"][lab.MGMT_NETWORK]["external"] is True, name
        ips = [
            svc["networks"][lab.MGMT_NETWORK]["ipv4_address"]
            for svc in compose["services"].values()
            if isinstance(svc.get("networks"), dict) and lab.MGMT_NETWORK in svc["networks"]
        ]
        assert ips == [lab.SERVICE_IPS[name], *lab.SERVICE_EXTRA_IPS.get(name, [])], name


def test_service_ips_are_unique() -> None:
    ips = [*lab.SERVICE_IPS.values(), *(ip for extra in lab.SERVICE_EXTRA_IPS.values() for ip in extra)]
    assert len(set(ips)) == len(ips)


# --------------------------------------------------------------------------- oxidized


def _router_db() -> list[list[str]]:
    path = services.load("oxidized", env={}).directory / "router.db"
    return [line.split(":") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_oxidized_inventory_matches_topology() -> None:
    topo = yaml.safe_load(paths.topology_path("base").read_text(encoding="utf-8"))["topology"]["nodes"]
    expected = {
        name: (node["mgmt-ipv4"], "srlinux" if node["kind"] == "nokia_srlinux" else "frr")
        for name, node in topo.items()
        if not name.startswith("h")  # hosts aren't backed up
    }
    assert {row[0]: (row[1], row[2]) for row in _router_db()} == expected


def test_oxidized_models_exist_for_inventory() -> None:
    model_dir = services.load("oxidized", env={}).directory / "model"
    for _, _, model, *_ in _router_db():
        assert (model_dir / f"{model}.rb").is_file(), model


def test_oxidized_reset_is_volume_based() -> None:
    spec = services.load("oxidized", env={})
    assert spec.snapshot is not None
    assert spec.snapshot.kind == "volumes"
    assert lifecycle.has_snapshot(spec)  # empty baseline always exists, no docker call needed


def test_volume_reset_commands(monkeypatch: Any) -> None:
    spec = services.load("oxidized", env={})
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> Any:
        calls.append(argv)

    monkeypatch.setattr(lifecycle, "_run", fake_run)
    monkeypatch.setattr(lifecycle, "wait_healthy", lambda spec, timeout: None)
    lifecycle.restore_snapshot(spec)
    assert calls[0][-4:] == ["rm", "--stop", "--force", "oxidized"]
    assert calls[1] == ["docker", "volume", "rm", "--force", "stick-oxidized_oxidized-output"]
    assert calls[2][-5:-2] == ["up", "-d", "--wait"]
