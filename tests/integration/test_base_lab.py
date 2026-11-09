"""Deploy the base lab and check the routing works. Needs Docker, containerlab and the stick-frr image.

Run with: uv run pytest -m lab
"""

from __future__ import annotations

import pytest
from labutil import dexec, frr_established_peers, wait_for

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


def test_frr_snmp_answers(lab: None) -> None:
    res = dexec("frr1", "snmpget", "-v2c", "-c", "stick-ro", "127.0.0.1", "SNMPv2-MIB::sysName.0")
    assert "frr1" in res.stdout
