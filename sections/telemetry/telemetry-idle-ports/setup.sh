#!/bin/bash
# A number of srl2's unused ports, which only this run knows, are enabled: nothing is connected, so they
# stay down. srl1 gets one too, which is not asked about.
set -euo pipefail
source "$STICK_LIB/common.sh"
telemetry_ready
ports=(7 12 4 19 9 15 3)
cmds=()
for i in $(seq 0 $((STICK_CANARY_PORTS - 1))); do cmds+=("set / interface ethernet-1/${ports[$i]} admin-state enable"); done
srl_commit "$STICK_NODE_SRL2" "${cmds[@]}"
srl_commit "$STICK_NODE_SRL1" "set / interface ethernet-1/5 admin-state enable"
prom_wait 'count(admin_state{source="srl2"} == 1 and oper_state{source="srl2"} == 0)' "$STICK_CANARY_PORTS"
prom_wait 'count(admin_state{source="srl1"} == 1 and oper_state{source="srl1"} == 0)' 1
prom_wait 'count(admin_state{source="srl2"} == 1 and oper_state{source="srl2"} == 1)' 2
