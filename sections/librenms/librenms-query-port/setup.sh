#!/bin/bash
# Both SR Linux nodes get a random host name and one described port each (the answer is srl2's); LibreNMS
# monitors them and frr1, and has polled them, so the descriptions and names are in its database.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL1" "set / system name host-name ${STICK_CANARY_N1}"
srl_set "$STICK_NODE_SRL2" "set / system name host-name ${STICK_CANARY_N2}"
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/7 description ${STICK_CANARY_OTHER}"
srl_set "$STICK_NODE_SRL2" "set / interface ethernet-1/7 description ${STICK_CANARY_DESC}"
for check in "$STICK_NODE_SRL1_IP $STICK_CANARY_N1" "$STICK_NODE_SRL1_IP $STICK_CANARY_OTHER" \
    "$STICK_NODE_SRL2_IP $STICK_CANARY_N2" "$STICK_NODE_SRL2_IP $STICK_CANARY_DESC"; do
    librenms_wait_snmp "${check% *}" stick-ro "${check#* }"
done
librenms_add_devices stick-ro "$STICK_NODE_SRL1_IP" "$STICK_NODE_SRL2_IP" "$STICK_NODE_FRR1_IP"
