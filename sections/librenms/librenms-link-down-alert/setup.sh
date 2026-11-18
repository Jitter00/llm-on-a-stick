#!/bin/bash
# frr2 shuts its eth2, so srl2's ethernet-1/2 ("to frr2") loses its carrier while it stays enabled. On srl1, a
# spare port that leads nowhere is enabled (down), and a port for a planned link is described "to ..." but
# stays disabled (SR Linux would enable an interface created for a description alone). LibreNMS monitors srl1,
# frr1 and frr2; srl2 is not in it yet.
set -euo pipefail
source "$STICK_LIB/common.sh"
ports=(7 12 4 19 9 15 3)
spare="ethernet-1/${ports[$((STICK_CANARY_SPARE - 3))]}"
planned="ethernet-1/$((STICK_CANARY_SPARE + 20))"
srl_commit "$STICK_NODE_SRL1" "set / interface $spare admin-state enable" "set / interface $spare description spare" \
    "set / interface $planned admin-state disable" \
    "set / interface $planned description \"to $STICK_CANARY_PLANNED (planned)\""
frr_conf "$STICK_NODE_FRR2" "interface eth2" "shutdown"
librenms_wait_snmp "$STICK_NODE_SRL1_IP" stick-ro "$STICK_CANARY_PLANNED"
librenms_add_devices stick-ro "$STICK_NODE_SRL1_IP" "$STICK_NODE_FRR1_IP" "$STICK_NODE_FRR2_IP"
