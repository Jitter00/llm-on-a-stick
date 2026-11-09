"""Deploy the base lab and check the routing works. Needs Docker, containerlab and the stick-frr image.

Run with: uv run pytest -m lab
"""

from __future__ import annotations

import pytest
from labutil import dexec, frr_established_peers, wait_for

from llm_on_a_stick.grading.labstate import DockerLabState

pytestmark = pytest.mark.lab


@pytest.mark.parametrize("leaf", ["frr1", "frr2"])
def test_leaf_has_both_spine_sessions(lab: None, leaf: str) -> None:
    assert wait_for(lambda: frr_established_peers(leaf) == 2), f"{leaf}: BGP sessions to both spines not up"


def test_host_to_host_ping(lab: None) -> None:
    assert wait_for(lambda: dexec("h1", "ping", "-c", "2", "-W", "2", "10.1.2.10").returncode == 0)


def test_frr_cli_user_lands_in_vtysh(lab: None) -> None:
    res = dexec("frr1", "getent", "passwd", "admin")
    assert res.stdout.strip().endswith("/usr/bin/vtysh")


def test_frr_cli_output_is_clean(lab: None) -> None:
    """A non-root vtysh session must not print config-file warnings before the real output."""
    res = dexec("frr1", "su", "-s", "/bin/sh", "admin", "-c", 'vtysh -c "show running-config"')
    assert res.returncode == 0
    assert "Can't open" not in res.stdout + res.stderr
    assert "processing failure" not in res.stdout + res.stderr
    assert "router bgp 65101" in res.stdout


def test_frr_shell_user_reads_lldp(lab: None) -> None:
    """`netops` has a Linux shell and may use lldpd's socket: frr1 hears an SR Linux neighbour on eth1."""
    shell = dexec("frr1", "getent", "passwd", "netops")
    assert shell.stdout.strip().endswith("/bin/bash")

    def heard() -> bool:
        res = dexec("frr1", "su", "-s", "/bin/sh", "netops", "-c", "lldpcli -f json show neighbors")
        return res.returncode == 0 and '"eth1"' in res.stdout and "ethernet-1/1" in res.stdout

    assert wait_for(heard, timeout=90), "frr1 heard no LLDP neighbour on eth1 (as netops)"


def test_restore_config_undoes_changes(lab: None) -> None:
    """`stick task start` puts every router back to its boot config, without restarting it: BGP stays up."""
    state = DockerLabState()
    for node in ("srl1", "frr1"):
        state.restore_config(node)
    boot = {node: state.running_config(node) for node in ("srl1", "frr1")}

    dexec("srl1", "sr_cli", "-ec", "set / interface ethernet-1/2 description stick-junk")
    dexec("srl1", "sr_cli", "-ec", "set / system name host-name stick-renamed")
    dexec("frr1", "vtysh", "-c", "conf t", "-c", "interface eth3", "-c", "description stick-junk",
          "-c", "exit", "-c", "ip prefix-list STICK-JUNK seq 5 permit 192.0.2.0/24")  # fmt: skip
    assert all("stick-junk" in state.running_config(node) for node in ("srl1", "frr1"))

    for node in ("srl1", "frr1"):
        state.restore_config(node)
    assert {node: state.running_config(node) for node in ("srl1", "frr1")} == boot
    assert wait_for(lambda: set(state.bgp_sessions("frr1").values()) == {"established"}, timeout=60)


def test_frr_snmp_answers(lab: None) -> None:
    res = dexec("frr1", "snmpget", "-v2c", "-c", "stick-ro", "127.0.0.1", "SNMPv2-MIB::sysName.0")
    assert "frr1" in res.stdout
