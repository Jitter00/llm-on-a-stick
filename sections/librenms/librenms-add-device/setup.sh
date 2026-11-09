#!/bin/bash
# srl1 answers SNMP only with this run's community; LibreNMS already monitors frr1.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_snmp_community "$STICK_NODE_SRL1" "$STICK_CANARY_COMMUNITY"
librenms_wait_snmp "$STICK_NODE_SRL1_IP" "$STICK_CANARY_COMMUNITY" srl1
librenms_add_device "$STICK_NODE_FRR1_IP" stick-ro
