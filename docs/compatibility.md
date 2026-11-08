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
| SSH CLI | ✅ (`admin`/`NokiaSrl1!`; exec mode works) | ✅ (lands in vtysh; clean output) | `test_oxidized.py`, `test_frr_cli_output_is_clean` |
| SNMPv2c | ❓ | ✅ | `test_frr_snmp_answers` |
| NETCONF | ✅ port 830, base:1.0 framing, subtree filters (`get-config` on running) | ❌ (FRR has no NETCONF server) | `test_tasks_lab.py` (netconf tasks) |
| gNMI | ❓ | ❌ (no native gNMI) | – |
| LLDP | ❓ | ❓ | – |
| Remote syslog | ❓ | ❓ | – |
| Measured RAM (idle) | 1870 MiB | 31 MiB | cgroup `memory.current` |

## Tools

Filled in as each service is added (Phase 0, step 3).

| Tool | SR Linux | FRR | Notes |
|---|---|---|---|
| NetBox 4.7.4 | n/a | n/a | ✅ up, seeded, reachable from `stick-mgmt` at 172.30.30.100:8080; reset verified (`tests/integration/test_netbox.py`) |
| Nautobot | n/a | n/a | |
| LibreNMS (SNMP) | ❓ | ❓ | |
| Zabbix (SNMP) | ❓ | ❓ | |
| Oxidized 0.37.0 | ✅ custom model | ✅ custom model | Oxidized ships neither; ours are in `services/oxidized/model/` (`test_oxidized.py`) |
| Batfish | ❓ (expected ❌) | ❓ (expected ⚠️) | Batfish isn't known to parse SR Linux; FRR support is partial |
| SuzieQ | ❓ | ❓ | |
| gNMIc + Prometheus | ❓ | ❌ | FRR telemetry would come over SNMP instead |
| Loki (syslog) | ❓ | ❓ | |
| PowerDNS / Kea | n/a | n/a | Hosts would use Kea for DHCP |
| Gitea | n/a | n/a | Config repo for GitOps-style tasks |
