#!/bin/bash
# frr2 gets two route-maps on its sessions, neither of which changes routing: STICK-CORE (inbound from both
# spines) matches on a prefix-list that exists; the one named for this run (outbound to srl2) has three
# entries, and the middle one (25) matches on a prefix-list that frr2 doesn't have (FRR takes that as "no
# match" and goes on to the last entry, which permits everything). Two things to tell apart from it: frr1
# does have a prefix-list of that name (in a route-map that isn't applied), and frr1 has a route-map that
# matches on an undefined AS-path list. Then the lab goes into Batfish as the snapshot "current".
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR1" \
    "ip prefix-list $STICK_CANARY_PLIST seq 5 permit 10.1.0.0/16 le 24" \
    "route-map STICK-HOSTS permit 10" "match ip address prefix-list $STICK_CANARY_PLIST" "exit" \
    "route-map STICK-TRANSIT deny 10" "match as-path STICK-UPSTREAMS" "exit" \
    "route-map STICK-TRANSIT permit 20"
frr_conf "$STICK_NODE_FRR2" \
    "ip prefix-list STICK-LOOPBACKS seq 5 permit 10.255.0.0/16 le 32" \
    "route-map STICK-CORE permit 10" "match ip address prefix-list STICK-LOOPBACKS" "exit" \
    "route-map STICK-CORE permit 20" "exit" \
    "route-map $STICK_CANARY_RMAP permit 10" "match ip address prefix-list STICK-LOOPBACKS" "exit" \
    "route-map $STICK_CANARY_RMAP permit 25" "match ip address prefix-list $STICK_CANARY_PLIST" "exit" \
    "route-map $STICK_CANARY_RMAP permit 40" "exit" \
    "router bgp 65102" "address-family ipv4 unicast" \
    "neighbor 10.0.1.2 route-map STICK-CORE in" "neighbor 10.0.2.2 route-map STICK-CORE in" \
    "neighbor 10.0.2.2 route-map $STICK_CANARY_RMAP out"
bf_snapshot current
