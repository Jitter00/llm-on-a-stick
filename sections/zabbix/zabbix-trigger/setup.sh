#!/bin/bash
# The description is on a port that is down (srl1 ethernet-1/5, unused) and on one that is up (srl2
# ethernet-1/1, a spine-leaf link). Zabbix has discovered both: each port has its own items there, named
# after the port and its description.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/5 description ${STICK_CANARY_DESC}"
srl_set "$STICK_NODE_SRL2" "set / interface ethernet-1/1 description ${STICK_CANARY_DESC}"
snmp_wait "$STICK_NODE_SRL1_IP" stick-ro "$STICK_CANARY_DESC"
snmp_wait "$STICK_NODE_SRL2_IP" stick-ro "$STICK_CANARY_DESC"
zabbix_add_host srl1 "$STICK_NODE_SRL1_IP" stick-ro >/dev/null
zabbix_add_host srl2 "$STICK_NODE_SRL2_IP" stick-ro >/dev/null
for host in srl1 srl2; do
    zabbix_wait_available "$host" 1
    zabbix_wait_items "$host" "$STICK_CANARY_DESC"
done
zabbix_poll srl1 net.if.status
zabbix_poll srl2 net.if.status
sleep 5
