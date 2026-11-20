#!/bin/bash
# The lab goes into Batfish as "current". Then the proposed change is made on the routers, dumped as
# "candidate" and undone. Three sessions break, and Batfish's status alone doesn't give the cause:
#   frr1 to srl1: frr1's link address becomes one of this run's (srl1 still expects 10.0.1.1): no local address
#   frr2 to srl1: frr2's neighbour is one of this run's addresses instead of 10.0.1.2: also "no local address"
#   frr1 to srl2: frr1 presents an AS of this run to srl2 (local-as; srl2 expects 65101): half open, which is
#                 also what a wrong remote-as gives
# frr2's session to srl2 gets a new description and timers, and frr1's host-facing interface a new
# description: those break nothing. The lab runs as before; only Batfish has the candidate.
set -euo pipefail
source "$STICK_LIB/common.sh"
bf_snapshot current
frr_conf "$STICK_NODE_FRR1" "interface eth1" "no ip address 10.0.1.1/31" "ip address $STICK_CANARY_ADDR/31" "exit" \
    "interface eth3" "description to h1 (hosts)" "exit" \
    "router bgp 65101" "neighbor 10.0.2.0 local-as $STICK_CANARY_ASN no-prepend replace-as"
frr_conf "$STICK_NODE_FRR2" "router bgp 65102" "no neighbor 10.0.1.2" \
    "neighbor $STICK_CANARY_PEER remote-as 65001" "neighbor $STICK_CANARY_PEER description srl1" \
    "neighbor 10.0.2.2 description srl2 (spine 2)" "neighbor 10.0.2.2 timers 10 30"
bf_snapshot candidate
frr_conf "$STICK_NODE_FRR1" "interface eth1" "no ip address $STICK_CANARY_ADDR/31" "ip address 10.0.1.1/31" "exit" \
    "interface eth3" "description to h1" "exit" \
    "router bgp 65101" "no neighbor 10.0.2.0 local-as"
frr_conf "$STICK_NODE_FRR2" "router bgp 65102" "no neighbor $STICK_CANARY_PEER" \
    "neighbor 10.0.1.2 remote-as 65001" "neighbor 10.0.1.2 description srl1" \
    "neighbor 10.0.2.2 description srl2" "no neighbor 10.0.2.2 timers"
