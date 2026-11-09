#!/bin/bash
# LibreNMS monitors all four routers; then srl2's community changes on the router, and the next poll finds
# it down.
set -euo pipefail
source "$STICK_LIB/common.sh"
librenms_add_devices stick-ro "$STICK_NODE_SRL1_IP" "$STICK_NODE_SRL2_IP" "$STICK_NODE_FRR1_IP" "$STICK_NODE_FRR2_IP"
srl_snmp_community "$STICK_NODE_SRL2" "$STICK_CANARY_COMMUNITY"
librenms_wait_snmp "$STICK_NODE_SRL2_IP" "$STICK_CANARY_COMMUNITY" srl2
librenms_poll "$STICK_NODE_SRL2_IP"
