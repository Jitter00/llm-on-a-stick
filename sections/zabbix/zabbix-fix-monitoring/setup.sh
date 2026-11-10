#!/bin/bash
# Zabbix monitors all four routers, each with its community in the host macro {$SNMP_COMMUNITY}; then
# srl2's community changes on the router, and Zabbix stops reaching it.
set -euo pipefail
source "$STICK_LIB/common.sh"
for node in SRL1 SRL2 FRR1 FRR2; do
    ip="STICK_NODE_${node}_IP"
    zabbix_add_host "${node,,}" "${!ip}" stick-ro >/dev/null
done
for host in srl1 srl2 frr1 frr2; do zabbix_wait_available "$host" 1; done
srl_snmp_community "$STICK_NODE_SRL2" "$STICK_CANARY_COMMUNITY"
snmp_wait "$STICK_NODE_SRL2_IP" "$STICK_CANARY_COMMUNITY" srl2
zabbix_wait_available srl2 2
