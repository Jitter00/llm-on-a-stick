#!/bin/bash
# frr1 gets five /24s of this run on its loopback and frr2 two (redistributed into BGP like every connected
# network), and route-maps on the sessions decide which spine carries each:
#   both       frr1's, through both spines
#   only_srl2  frr1's, not announced to srl1: frr2 has its /24 through srl2 only
#   only_srl1  frr1's, announced to both, but frr2 doesn't accept it from srl2: through srl1 only
#   never      frr1's, announced to neither spine: frr2 has no /24 route to it
#   decoy      frr1's; the prefix-lists name it, but as a /25 and as "/24 ge 25", which don't match the /24:
#              through both spines
#   back_srl2  frr2's, which frr1 doesn't accept from srl1: frr1 has it through srl2 only
#   back_both  frr2's, through both spines
#   back_hole  frr2's, through both spines, but frr1 has a static blackhole for its lower /25: frr1 has a /24
#              route and can't reach .1 today, so it can't lose it
# frr1 also announces 198.19.0.0/16 (a static blackhole, redistributed), to srl1 only. So the /24 routes
# alone mislead: with srl2 down frr2 loses the /24 of only_srl2 and still reaches it through the /16 by
# srl1; frr2 reaches `never` today through the /16, and loses it (with only_srl1) when srl1 is down.
# Then the lab goes into Batfish as "current".
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR1" \
    "ip prefix-list STICK-NOT-SRL1 seq 5 permit $STICK_CANARY_ONLY_SRL2.0/24" \
    "ip prefix-list STICK-NOT-SRL1 seq 10 permit $STICK_CANARY_NEVER.0/24" \
    "ip prefix-list STICK-NOT-SRL1 seq 15 permit $STICK_CANARY_DECOY.0/25" \
    "ip prefix-list STICK-NOT-SRL2 seq 5 permit $STICK_CANARY_NEVER.0/24" \
    "ip prefix-list STICK-NOT-SRL2 seq 10 permit $STICK_CANARY_DECOY.0/24 ge 25" \
    "ip prefix-list STICK-NOT-SRL2 seq 15 permit 198.19.0.0/16" \
    "ip prefix-list STICK-AGGREGATE seq 5 permit 198.19.0.0/16" \
    "route-map STICK-AGGREGATE permit 10" "match ip address prefix-list STICK-AGGREGATE" "exit" \
    "ip route 198.19.0.0/16 blackhole" "ip route $STICK_CANARY_BACK_HOLE.0/25 blackhole" \
    "ip prefix-list STICK-NOT-FROM-SRL1 seq 5 permit $STICK_CANARY_BACK_SRL2.0/24" \
    "route-map STICK-TO-SRL1 deny 10" "match ip address prefix-list STICK-NOT-SRL1" "exit" \
    "route-map STICK-TO-SRL1 permit 20" "exit" \
    "route-map STICK-TO-SRL2 deny 10" "match ip address prefix-list STICK-NOT-SRL2" "exit" \
    "route-map STICK-TO-SRL2 permit 20" "exit" \
    "route-map STICK-FROM-SRL1 deny 10" "match ip address prefix-list STICK-NOT-FROM-SRL1" "exit" \
    "route-map STICK-FROM-SRL1 permit 20" "exit" \
    "router bgp 65101" "address-family ipv4 unicast" "redistribute static route-map STICK-AGGREGATE" \
    "neighbor 10.0.1.0 route-map STICK-TO-SRL1 out" "neighbor 10.0.1.0 route-map STICK-FROM-SRL1 in" \
    "neighbor 10.0.2.0 route-map STICK-TO-SRL2 out" "exit-address-family" "exit" \
    "interface lo" "ip address $STICK_CANARY_BOTH.1/24" "ip address $STICK_CANARY_ONLY_SRL2.1/24" \
    "ip address $STICK_CANARY_ONLY_SRL1.1/24" "ip address $STICK_CANARY_NEVER.1/24" \
    "ip address $STICK_CANARY_DECOY.1/24"
frr_conf "$STICK_NODE_FRR2" \
    "ip prefix-list STICK-NOT-FROM-SRL2 seq 5 permit $STICK_CANARY_ONLY_SRL1.0/24" \
    "route-map STICK-FROM-SRL2 deny 10" "match ip address prefix-list STICK-NOT-FROM-SRL2" "exit" \
    "route-map STICK-FROM-SRL2 permit 20" "exit" \
    "router bgp 65102" "address-family ipv4 unicast" "neighbor 10.0.2.2 route-map STICK-FROM-SRL2 in" \
    "exit-address-family" "exit" \
    "interface lo" "ip address $STICK_CANARY_BACK_SRL2.1/24" "ip address $STICK_CANARY_BACK_BOTH.1/24" \
    "ip address $STICK_CANARY_BACK_HOLE.1/24"
bf_snapshot current
