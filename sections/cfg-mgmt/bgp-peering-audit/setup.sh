#!/bin/bash
# Two neighbours get a wrong AS, one on each vendor: srl1's neighbour 10.0.1.3 (frr2, really 65102) and
# frr1's neighbour 10.0.2.0 (srl2, really 65002). The wrong numbers are this run's, as 4-byte private ASNs
# ("42000" before a canary), so they can't be one of the lab's own.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL1" \
    "set / network-instance default protocols bgp neighbor 10.0.1.3 peer-as 42000${STICK_CANARY_SRL_AS}"
frr_conf "$STICK_NODE_FRR1" "router bgp 65101" "neighbor 10.0.2.0 remote-as 42000${STICK_CANARY_FRR_AS}"
