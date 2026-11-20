#!/bin/bash
# frr2 expects its neighbour srl2 in an AS that only this run knows (srl2 is in 65002), so that session never
# comes up. SR Linux isn't polled: SuzieQ sees it from frr2's side only, as a session that isn't established.
set -euo pipefail
source "$STICK_LIB/common.sh"
sq_ready
frr_conf "$STICK_NODE_FRR2" "router bgp 65102" "neighbor 10.0.2.2 remote-as $STICK_CANARY_ASN"
sq_wait 'map(select(.state != "Established")) | map([.hostname, .peer, .peerAsn]) == [["frr2", "10.0.2.2", '"$STICK_CANARY_ASN"']]' bgp show
