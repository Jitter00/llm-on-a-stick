#!/bin/bash
# Put this run's canaries inside the BGP sections, so the answer can't be recited from memory.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL2" \
    "set / network-instance default protocols bgp neighbor 10.0.2.1 description ${STICK_CANARY_SRL_PEER_DESC}"
frr_conf "$STICK_NODE_FRR1" "router bgp 65101" "neighbor 10.0.1.0 description ${STICK_CANARY_FRR_PEER_DESC}"
