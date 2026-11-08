#!/bin/bash
# Add this run's canary address to frr1's loopback, after removing canaries from earlier runs
# (all canary addresses come from 198.18.0.0/15, the benchmarking range).
set -euo pipefail
source "$STICK_LIB/common.sh"
old=$(frr_cli "$STICK_NODE_FRR1" "show running-config" \
    | awk '/^interface lo$/ {inside=1; next} inside && /^exit$/ {inside=0} inside && /ip address 198\.1[89]\./ {print $3}')
for addr in $old; do
    frr_conf "$STICK_NODE_FRR1" "interface lo" "no ip address ${addr}"
done
frr_conf "$STICK_NODE_FRR1" "interface lo" "ip address ${STICK_CANARY_LOOPBACK_IP}/32"
