#!/bin/bash
# srl1 answers SNMP with this run's community only; Zabbix already monitors frr1 (which must stay as it is).
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_snmp_community "$STICK_NODE_SRL1" "$STICK_CANARY_COMMUNITY"
snmp_wait "$STICK_NODE_SRL1_IP" "$STICK_CANARY_COMMUNITY" srl1
zabbix_add_host frr1 "$STICK_NODE_FRR1_IP" stick-ro >/dev/null
zabbix_wait_available frr1 1
