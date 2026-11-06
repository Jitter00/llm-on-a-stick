# Compatibility matrix

Which tool works with which lab device. Each cell is filled in from a real test, not from documentation.

Legend: ✅ verified · ⚠️ partial (see notes) · ❌ doesn't work · ❓ not tested yet

## Devices

| Check | SR Linux 26.7.2 | stick-frr (FRR 10.7.1) | Verified by |
|---|---|---|---|
| Boots in containerlab 0.82.0 | ✅ | ✅ | `pytest -m lab` |
| eBGP spine/leaf sessions up | ✅ | ✅ | `test_leaf_has_both_spine_sessions` |
| Host-to-host traffic across the fabric | ✅ | ✅ | `test_host_to_host_ping` |
| arm64 image available | ✅ | ✅ | registry manifest lists |
| SSH CLI | ❓ | ✅ (lands in vtysh) | `test_frr_cli_user_lands_in_vtysh` |
| SNMPv2c | ❓ | ✅ | `test_frr_snmp_answers` |
| NETCONF | ❓ | ❌ (FRR has no NETCONF server) | – |
| gNMI | ❓ | ❌ (no native gNMI) | – |
| LLDP | ❓ | ❓ | – |
| Remote syslog | ❓ | ❓ | – |
| Measured RAM (idle) | 1870 MiB | 31 MiB | cgroup `memory.current` |

## Tools

To be filled in as each service is added (Phase 0, step 3).

| Tool | SR Linux | FRR | Notes |
|---|---|---|---|
| NetBox / Nautobot | n/a | n/a | Source of truth; device-side checks only if LLDP discovery is used |
| LibreNMS (SNMP) | ❓ | ❓ | |
| Zabbix (SNMP) | ❓ | ❓ | |
| Oxidized | ❓ | ❓ | Check which Oxidized model fits each OS |
| Batfish | ❓ (expected ❌) | ❓ (expected ⚠️) | Batfish isn't known to parse SR Linux; FRR support is partial |
| SuzieQ | ❓ | ❓ | |
| gNMIc + Prometheus | ❓ | ❌ | FRR telemetry would come over SNMP instead |
| Loki (syslog) | ❓ | ❓ | |
| PowerDNS / Kea | n/a | n/a | Hosts would use Kea for DHCP |
| Gitea | n/a | n/a | Config repo for GitOps-style tasks |
