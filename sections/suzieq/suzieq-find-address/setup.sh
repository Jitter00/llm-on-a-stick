#!/bin/bash
# frr2 gets this run's /26 on its host-facing interface (a second address on eth3, redistributed into BGP
# like every connected network), but doesn't announce it to srl1: frr1 reaches it through srl2 only, while
# every BGP session stays up. The host the alert names is in that /26 but is no router's address, so a search
# for the address itself finds nothing. frr1 has the /24 around it on its loopback: the network that contains
# the host, but not the most specific one.
set -euo pipefail
source "$STICK_LIB/common.sh"
sq_ready
frr_conf "$STICK_NODE_FRR2" \
    "ip prefix-list STICK-ALERT seq 5 permit $STICK_CANARY_NET.0/26" \
    "route-map STICK-TO-SRL1 deny 10" "match ip address prefix-list STICK-ALERT" "exit" \
    "route-map STICK-TO-SRL1 permit 20" "exit" \
    "router bgp 65102" "address-family ipv4 unicast" "neighbor 10.0.1.2 route-map STICK-TO-SRL1 out" \
    "exit-address-family" "exit" \
    "interface eth3" "ip address $STICK_CANARY_NET.1/26"
frr_conf "$STICK_NODE_FRR1" "interface lo" "ip address $STICK_CANARY_NET.200/24"
sq_wait 'length == 1 and .[0].ifname == "eth3"' address show hostname=frr2 address="$STICK_CANARY_NET.1"
sq_wait 'length == 1 and .[0].nexthopIps == ["10.0.2.0"]' route show hostname=frr1 prefix="$STICK_CANARY_NET.0/26"
sq_wait 'length == 1' address show hostname=frr1 address="$STICK_CANARY_NET.200"
