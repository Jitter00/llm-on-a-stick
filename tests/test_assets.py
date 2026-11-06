"""Static checks on the lab assets, so a broken topology fails in CI before anyone deploys it."""

from __future__ import annotations

from pathlib import Path

import yaml

from llm_on_a_stick import footprints, paths

TOPO = paths.topology_path("base")


def load_topology() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(TOPO.read_text(encoding="utf-8"))


def test_every_link_endpoint_is_a_defined_node() -> None:
    topo = load_topology()["topology"]
    nodes = set(topo["nodes"])
    for link in topo["links"]:
        for ep in link["endpoints"]:
            assert ep.split(":")[0] in nodes, ep


def test_no_interface_used_twice() -> None:
    eps = [ep for link in load_topology()["topology"]["links"] for ep in link["endpoints"]]
    assert len(eps) == len(set(eps))


def test_referenced_config_files_exist() -> None:
    for name, node in load_topology()["topology"]["nodes"].items():
        refs = [node["startup-config"]] if "startup-config" in node else []
        refs += [b.split(":")[0] for b in node.get("binds", [])]
        for ref in refs:
            assert (TOPO.parent / ref).resolve().is_file(), f"{name}: {ref}"


def test_frr_config_mounts_are_read_only() -> None:
    for name, node in load_topology()["topology"]["nodes"].items():
        for bind in node.get("binds", []):
            assert bind.endswith(":ro"), (
                f"{name}: {bind} must be read-only so `write memory` can't edit the repo"
            )


def test_srlinux_image_matches_footprints() -> None:
    kinds = load_topology()["topology"]["kinds"]
    assert kinds["nokia_srlinux"]["image"] == footprints.load().images["srlinux"].image


def test_footprint_node_counts_match_topology() -> None:
    nodes = load_topology()["topology"]["nodes"]
    srl = sum(1 for n in nodes.values() if n["kind"] == "nokia_srlinux")
    hosts = sum(1 for n in nodes.values() if "network-multitool" in n.get("image", ""))
    frr = len(nodes) - srl - hosts
    assert footprints.load().topologies["base"].nodes == {
        "srlinux": srl,
        "stick-frr": frr,
        "multitool": hosts,
    }


def test_frr_image_build_context() -> None:
    ctx = paths.image_dir("frr")
    for f in ("Dockerfile", "stick-entrypoint.sh", "snmpd.conf", "rsyslog.conf"):
        assert (ctx / f).is_file(), f
    dockerfile = (ctx / "Dockerfile").read_text(encoding="utf-8")
    copied = [line.split()[-2] for line in dockerfile.splitlines() if line.startswith("COPY")]
    for src in copied:
        assert (ctx / Path(src)).is_file(), f"Dockerfile copies missing file {src}"
