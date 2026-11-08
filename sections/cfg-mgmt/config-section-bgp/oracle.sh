#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_cli "$STICK_NODE_SRL2" "info flat" \
    | grep '^set / network-instance default protocols bgp ' > "$STICK_WORKSPACE/srl2-bgp.cfg"
frr_cli "$STICK_NODE_FRR1" "show running-config" \
    | awk '/^router bgp/ {inside=1} inside {print} inside && /^exit$/ {inside=0}' > "$STICK_WORKSPACE/frr1-bgp.cfg"
