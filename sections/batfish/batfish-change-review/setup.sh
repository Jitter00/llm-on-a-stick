#!/bin/bash
# frr1 has three networks of this run on its loopback: the test /24, another /24 in use and a /25, all in
# 198.19.0.0/16. frr2 has two /24s; it doesn't announce one of them to srl1 (as it runs today), so frr1 has
# that one through srl2 only. The lab goes into Batfish as "current". Then the proposed change is made on
# frr1, dumped as "candidate" and undone: a new /24 on the loopback, and a route-map with two mistakes. Its
# prefix-list denies all of 198.19.0.0/16 up to /24 instead of the test network alone, and it is outbound on
# the session to srl1 but inbound on the session to srl2. The candidate also has something the request
# doesn't mention: a static route for one more /24 of this run towards srl1, redistributed into BGP. srl2
# hears it from frr1, frr2 from srl2 and srl1 from frr2, so packets to it go round: frr1, srl1, frr2, srl2,
# frr1. So in the candidate:
#   frr2 keeps the test network and the other /24, through srl2 only; gets the new /24, through srl2 only;
#        gets the looping /24, through srl2 only; keeps the /25 through both spines
#   frr1 loses frr2's network that only comes through srl2, and keeps the other through srl1 only
# The lab runs as before.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR1" "interface lo" "ip address $STICK_CANARY_TEST.1/24" "ip address $STICK_CANARY_PROD.1/24" \
    "ip address $STICK_CANARY_QUARTER.129/25"
frr_conf "$STICK_NODE_FRR2" \
    "ip prefix-list STICK-NOT-SRL1 seq 5 permit $STICK_CANARY_FAR_SINGLE.0/24" \
    "route-map STICK-TO-SRL1 deny 10" "match ip address prefix-list STICK-NOT-SRL1" "exit" \
    "route-map STICK-TO-SRL1 permit 20" "exit" \
    "router bgp 65102" "address-family ipv4 unicast" "neighbor 10.0.1.2 route-map STICK-TO-SRL1 out" \
    "exit-address-family" "exit" \
    "interface lo" "ip address $STICK_CANARY_FAR.1/24" "ip address $STICK_CANARY_FAR_SINGLE.1/24"
bf_snapshot current
frr_conf "$STICK_NODE_FRR1" \
    "ip prefix-list STICK-NO-TEST seq 5 deny 198.19.0.0/16 le 24" \
    "ip prefix-list STICK-NO-TEST seq 10 permit 0.0.0.0/0 le 32" \
    "route-map STICK-NO-TEST permit 10" "match ip address prefix-list STICK-NO-TEST" "exit" \
    "ip route $STICK_CANARY_LOOP.0/24 10.0.1.0" \
    "router bgp 65101" "address-family ipv4 unicast" "redistribute static" \
    "neighbor 10.0.1.0 route-map STICK-NO-TEST out" "neighbor 10.0.2.0 route-map STICK-NO-TEST in" \
    "exit-address-family" "exit" "interface lo" "ip address $STICK_CANARY_NEW.1/24"
bf_snapshot candidate
frr_conf "$STICK_NODE_FRR1" "router bgp 65101" "address-family ipv4 unicast" "no redistribute static" \
    "no neighbor 10.0.1.0 route-map STICK-NO-TEST out" "no neighbor 10.0.2.0 route-map STICK-NO-TEST in" \
    "exit-address-family" "exit" "no route-map STICK-NO-TEST" "no ip prefix-list STICK-NO-TEST" \
    "interface lo" "no ip address $STICK_CANARY_NEW.1/24" "exit" "no ip route $STICK_CANARY_LOOP.0/24 10.0.1.0"
