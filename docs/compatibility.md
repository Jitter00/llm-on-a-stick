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
| SSH CLI | ✅ (`admin`/`NokiaSrl1!`; exec mode works) | ✅ (`admin` lands in vtysh; clean output) | `test_oxidized.py`, `test_frr_cli_output_is_clean` |
| SSH Linux shell | – | ✅ (`netops`/`netops`: bash, `lldpcli`, `vtysh -c ...`) | `test_frr_shell_user_reads_lldp` |
| SNMPv2c | ✅ community `stick-ro` in the startup config (containerlab enables SNMP in `mgmt`); `ifAlias` = description | ✅ net-snmp; descriptions don't reach `ifAlias`, no BGP MIB | `test_srl_snmp_answers`, `test_frr_snmp_answers` |
| NETCONF | ✅ port 830, base:1.0 framing, subtree filters (`get-config` on running) | ❌ (FRR has no NETCONF server) | `test_tasks_lab.py` (netconf tasks) |
| gNMI | ❓ | ❌ (no native gNMI) | – |
| Restore boot config without a restart (`stick task start`) | ✅ checkpoint `clab-initial` revert (~0.5 s) | ✅ `frr-reload.py` against the startup file (~0.15 s) | `test_restore_config_undoes_changes` |
| LLDP | ✅ on by default; neighbours in `show system lldp neighbor`; sends its host name as system name | ✅ `lldpd`, read with `lldpcli` as `netops` (not from vtysh: FRR has no LLDP); port ID is the MAC unless `portidsubtype ifname` is set | `test_frr_shell_user_reads_lldp`, `test_tasks_lab.py` (`netbox-cables-lldp`) |
| Remote syslog | ✅ `system logging remote-server` in the `mgmt` network-instance, RFC 5424 over UDP; facility `local6` carries its own applications (commits with the user's name, every CLI command, port and BGP events), `auth` and `authpriv` the SSH logins | ✅ `rsyslog` beside FRR (`STICK_SYSLOG_TARGET`), RFC 5424 over UDP: `bgpd` neighbour changes, `sshd` logins. FRR does not log who changed its configuration, nor an interface going down by name | `test_loki.py` |
| Measured RAM (idle) | 1870 MiB | 31 MiB | cgroup `memory.current` |

## Tools

Filled in as each service is added (Phase 0, step 3).

| Tool | SR Linux | FRR | Notes |
|---|---|---|---|
| NetBox 4.7.4 | n/a | n/a | ✅ up, seeded, reachable from `stick-mgmt` at 172.30.30.100:8080; reset verified (`tests/integration/test_netbox.py`) |
| Nautobot 3.2.8 | n/a | n/a | ✅ up, seeded, reachable from `stick-mgmt` at 172.30.30.102:8080; reset verified (`tests/integration/test_nautobot.py`) |
| moto 5.2.5 (emulated AWS) | n/a | n/a | ✅ up, reachable from `stick-mgmt` at 172.30.30.103:5000; AWS CLI, boto3 and Terraform (offline provider) verified, reset verified (`tests/integration/test_moto.py`). Not verified: Terraform `aws_s3_bucket` (fails against an IP endpoint) |
| LibreNMS 26.10.2 | ✅ os `srlinux`, ports with descriptions | ✅ os `linux` (generic) | up, reachable from `stick-mgmt` at 172.30.30.104:8000; polls both, alert rules fire, reset verified (`tests/integration/test_librenms.py`) |
| Zabbix 8.0.0 | ✅ generic SNMP template, ports with descriptions | ✅ generic SNMP template | up, API reachable from `stick-mgmt` at 172.30.30.107:8080 (the server polls from .106); polls both, triggers raise problems, maintenance takes effect, reset verified (`tests/integration/test_zabbix.py`) |
| Oxidized 0.37.0 | ✅ custom model | ✅ custom model | Oxidized ships neither; ours are in `services/oxidized/model/` (`test_oxidized.py`) |
| MCP servers (NetBox 1.2.2, AWS API 1.6.0, nautobot-mcp 0.2.5, librenms-mcp 1.13.0, zabbix-mcp 0.8.0, mcp-grafana 2.2.0) | n/a | n/a | ✅ each starts against its service and solves its task (`check_mcp_server` in each service's lab tests, `test_tasks_lab.py`). zabbix-mcp supports Zabbix up to 7.4: with its version check off, the calls used work against 8.0. Not verified: the tools no task uses |
| Batfish | ❓ (expected ❌) | ❓ (expected ⚠️) | Batfish isn't known to parse SR Linux; FRR support is partial |
| SuzieQ | ❓ | ❓ | |
| gNMIc + Prometheus | ❓ | ❌ | FRR telemetry would come over SNMP instead |
| Loki 3.7.9 (Alloy 1.21.3, Grafana 13.3.1) | ✅ lines arrive with `host`, `app`, `severity` and `facility` labels | ✅ the same labels | up, syslog taken at 172.30.30.108:1514; reset verified (`tests/integration/test_loki.py`). SR Linux's gRPC server logs one warning a second (no TLS profile `EDA`): real noise that a query has to filter out |
| PowerDNS / Kea | n/a | n/a | Hosts would use Kea for DHCP |
| Gitea | n/a | n/a | Config repo for GitOps-style tasks |
