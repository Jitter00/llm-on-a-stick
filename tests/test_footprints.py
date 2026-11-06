from llm_on_a_stick import footprints


def test_base_topology_ram() -> None:
    fp = footprints.load()
    expected = sum(fp.images[img].ram_mb * n for img, n in fp.topologies["base"].nodes.items())
    assert fp.topology_ram_mb("base") == expected > 0


def test_base_topology_is_multi_arch() -> None:
    assert footprints.load().topology_arches("base") == {"amd64", "arm64"}


def test_services_subset() -> None:
    fp = footprints.load()
    assert (
        fp.services_ram_mb(["netbox", "gitea"]) == fp.services["netbox"].ram_mb + fp.services["gitea"].ram_mb
    )
    assert fp.services_ram_mb() >= fp.services_ram_mb(["netbox"])
