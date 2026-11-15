"""Lab instances: every name, address and port follows from one number."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from llm_on_a_stick import lab, paths, services
from llm_on_a_stick.grading.labstate import load_nodes
from llm_on_a_stick.services import lifecycle


def test_instance_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert lab.instance() == 0  # unset (tests/conftest.py clears it)
    monkeypatch.setenv(lab.INSTANCE_VAR, "2")
    assert lab.instance() == 2
    for bad in ("4", "-1", "one"):
        monkeypatch.setenv(lab.INSTANCE_VAR, bad)
        with pytest.raises(lab.InstanceError, match="0 to 3"):
            lab.instance()


def test_instance_0_is_the_lab_as_documented() -> None:
    assert lab.name(0) == "stick"
    assert (lab.mgmt_network(0), lab.mgmt_subnet(0)) == ("stick-mgmt", "172.30.30.0/24")
    assert lab.service_ips("loki", 0) == ["172.30.30.108", "172.30.30.111"]
    base = {"PATH": "/bin", "STICK_NETBOX_PORT": "9999"}
    assert lab.env(base, 0) == base  # nothing set: the files' defaults apply, a moved port stays moved


def test_another_instance_has_its_own_names_subnet_and_ports(tmp_path: Path) -> None:
    env = lab.env({"XDG_STATE_HOME": str(tmp_path), "STICK_NETBOX_PORT": "9999"}, 1)
    assert env["STICK_INSTANCE"] == "1"
    assert env["STICK_NAME"] == "stick1" == lab.name(1)
    assert env["STICK_MGMT_PREFIX"] == "172.30.31"
    assert (lab.mgmt_network(1), lab.mgmt_subnet(1)) == ("stick1-mgmt", "172.30.31.0/24")
    assert lab.service_ip("netbox", 1) == "172.30.31.100"
    assert env["STICK_NETBOX_PORT"] == "8181"  # derived, whatever the base says
    assert env["STICK_OXIDIZED_PORT"] == "8988"
    assert lab.env(env, 1) == env  # applying it twice changes nothing


def test_no_two_instances_share_a_port() -> None:
    ports = [port + 100 * n for n in range(lab.MAX_INSTANCES) for port in lab.PORTS.values()]
    assert len(set(ports)) == len(ports)


def test_ports_table_matches_the_service_files() -> None:
    """lab.PORTS repeats the defaults written in compose.yaml and service.yaml: they must agree."""
    found: dict[str, set[int]] = {}
    root = paths.assets_root() / "services"
    files = [*root.glob("*/compose.yaml"), *root.glob("*/service.yaml")]
    files.append(paths.sections_dir() / "_lib" / "common.sh")
    for path in files:
        for var, port in re.findall(r"\$\{(STICK_[A-Z]+_PORT):-(\d+)\}", path.read_text(encoding="utf-8")):
            found.setdefault(var, set()).add(int(port))
    assert found == {var: {port} for var, port in lab.PORTS.items()}


def test_files_without_variables_are_copied_with_the_instance_addresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert lab.render_instance_files(0) == []  # instance 0 reads the originals
    written = lab.render_instance_files(2)
    env = lab.env({}, 2)
    names = {"srl1.cli", "srl2.cli", "router.db", "gnmic.yaml", "datasources.yaml"}
    assert {p.name for p in written} == names
    for var, rel in lab.RENDERED.items():
        assert Path(env[var]).exists(), var
        assert (paths.assets_root() / rel).exists(), rel
    for path in written:
        text = path.read_text(encoding="utf-8")
        assert "172.30.30." not in text and "172.30.32." in text, path


def test_no_other_asset_holds_a_fixed_management_address() -> None:
    """A file with a literal 172.30.30.x works on instance 0 only: it needs a variable, or a place in
    lab.RENDERED. The exceptions are data no task compares with the lab."""
    rendered = [paths.assets_root() / rel for rel in lab.RENDERED.values()]
    allowed = {"services/nautobot/seed.yaml"}  # a seeded prefix, the same in every instance
    offenders = []
    for top in ("topologies", "services", "configs", "sections"):
        for path in (paths.assets_root() / top).rglob("*"):
            rel = path.relative_to(paths.assets_root()).as_posix()
            if not path.is_file() or rel in allowed or any(r == path or r in path.parents for r in rendered):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line in text.splitlines():
                bare = re.sub(r"\$\{STICK_MGMT_PREFIX:[-=]172\.30\.30\}", "", line)
                if "172.30.30." in bare and not bare.lstrip().startswith("#"):
                    offenders.append(f"{rel}: {line.strip()}")
    assert offenders == []


def test_nodes_and_compose_follow_the_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_nodes("base")["srl1"].container == "clab-stick-base-srl1"
    assert load_nodes("base")["h1"].mgmt_ipv4 == "172.30.30.31"
    monkeypatch.setenv(lab.INSTANCE_VAR, "1")
    nodes = load_nodes("base")
    assert nodes["srl1"].container == "clab-stick1-base-srl1"
    assert nodes["h1"].mgmt_ipv4 == "172.30.31.31"
    spec = services.load("netbox")
    assert lifecycle.compose_argv(spec, "ps")[:4] == ["docker", "compose", "-p", "stick1-netbox"]
    assert spec.health.url.startswith("http://127.0.0.1:8181/")
    assert "172.30.31.100" in spec.endpoints["api (lab mgmt network)"]
    routers = services.lab_mcp_servers()["routers"]
    hosts = yaml.safe_load(routers.env["STICK_NETMIKO_INVENTORY"])
    assert hosts["frr2"]["host"] == "172.30.31.22"


def test_lock_refuses_a_second_user_of_the_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    with lab.lock(1):
        with pytest.raises(lab.InstanceError, match="instance 1 is in use"), lab.lock(1):
            pass
        with lab.lock(2):  # another instance is free
            pass
    with lab.lock(1):  # released
        pass
