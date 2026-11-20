#!/bin/bash
# Several events a few seconds apart. First frr2's session to srl2 is shut down and brought back (it went down,
# and it is up again). Then frr1's host-facing interface gets a second address, which breaks nothing. Then
# frr1's link to srl1 gets one of this run's addresses instead of its own, so the session to srl1 goes down; a
# poll later the link's address is changed again, to another of this run's addresses, and the session stays
# down. The history has both drops and both of frr1's interface changes; only the address history of the link
# that faces the down session's neighbour says why, and what its address was while the session was up.
set -euo pipefail
source "$STICK_LIB/common.sh"
sq_ready
frr_conf "$STICK_NODE_FRR2" "router bgp 65102" "neighbor 10.0.2.2 shutdown"
sq_wait 'length == 1 and .[0].state != "Established"' bgp show hostname=frr2 peer=10.0.2.2
frr_conf "$STICK_NODE_FRR2" "router bgp 65102" "no neighbor 10.0.2.2 shutdown"
sq_wait 'length == 1 and .[0].state == "Established"' bgp show hostname=frr2 peer=10.0.2.2
frr_conf "$STICK_NODE_FRR1" "interface eth3" "ip address $STICK_CANARY_DECOY.1/24"
sq_wait 'length == 1 and (.[0].ipAddressList | index("'"$STICK_CANARY_DECOY"'.1/24"))' interface show hostname=frr1 ifname=eth3
frr_conf "$STICK_NODE_FRR1" "interface eth1" "no ip address 10.0.1.1/31" "ip address $STICK_CANARY_INTERIM/31"
sq_wait 'length == 1 and .[0].state != "Established"' bgp show hostname=frr1 peer=10.0.1.0
sq_wait 'length == 1 and .[0].ipAddressList == ["'"$STICK_CANARY_INTERIM"'/31"]' interface show hostname=frr1 ifname=eth1
frr_conf "$STICK_NODE_FRR1" "interface eth1" "no ip address $STICK_CANARY_INTERIM/31" "ip address $STICK_CANARY_ADDR/31"
sq_wait 'length == 1 and .[0].ipAddressList == ["'"$STICK_CANARY_ADDR"'/31"]' interface show hostname=frr1 ifname=eth1
