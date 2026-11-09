#!/bin/bash
# The description is on a port that is down (srl1 ethernet-1/5, unused) and on one that is up (srl2
# ethernet-1/1, a spine-leaf link). Dozens of other ports are down without it.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/5 description ${STICK_CANARY_DESC}"
srl_set "$STICK_NODE_SRL2" "set / interface ethernet-1/1 description ${STICK_CANARY_DESC}"
librenms_wait_snmp "$STICK_NODE_SRL1_IP" stick-ro "$STICK_CANARY_DESC"
librenms_wait_snmp "$STICK_NODE_SRL2_IP" stick-ro "$STICK_CANARY_DESC"
librenms_add_devices stick-ro "$STICK_NODE_SRL1_IP" "$STICK_NODE_SRL2_IP"
