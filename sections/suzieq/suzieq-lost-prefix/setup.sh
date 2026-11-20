#!/bin/bash
# frr2 has two of this run's /24s, redistributed into BGP: one on its host-facing interface (a second address
# on eth3), one on its loopback. Both stay long enough for SuzieQ to see them, on frr2 and as routes on frr1.
# Then both go away and frr2 starts announcing a third /24 from its loopback; a poll later the loopback one
# comes back. frr1's route history has two networks leaving, one coming back and one arriving: only one is
# still missing, and only the history of frr2's addresses says where it was.
set -euo pipefail
source "$STICK_LIB/common.sh"
sq_ready
frr_conf "$STICK_NODE_FRR2" "interface eth3" "ip address $STICK_CANARY_LOST.1/24" "exit" \
    "interface lo" "ip address $STICK_CANARY_FLAP.1/24"
sq_wait 'length == 1' route show hostname=frr1 prefix="$STICK_CANARY_LOST.0/24"
sq_wait 'length == 1' route show hostname=frr1 prefix="$STICK_CANARY_FLAP.0/24"
sq_wait 'length == 1 and .[0].ifname == "eth3"' address show hostname=frr2 address="$STICK_CANARY_LOST.1"
sleep 16  # one more poll with the networks in place, so that the history has them twice, like a real one would
frr_conf "$STICK_NODE_FRR2" "interface eth3" "no ip address $STICK_CANARY_LOST.1/24" "exit" \
    "interface lo" "no ip address $STICK_CANARY_FLAP.1/24" "ip address $STICK_CANARY_GAINED.1/24"
sq_wait 'length == 0' route show hostname=frr1 prefix="$STICK_CANARY_LOST.0/24"
sq_wait 'length == 0' route show hostname=frr1 prefix="$STICK_CANARY_FLAP.0/24"
sq_wait 'length == 1' route show hostname=frr1 prefix="$STICK_CANARY_GAINED.0/24"
sq_wait 'length == 0' address show hostname=frr2 address="$STICK_CANARY_LOST.1"
frr_conf "$STICK_NODE_FRR2" "interface lo" "ip address $STICK_CANARY_FLAP.1/24"
sq_wait 'length == 1' route show hostname=frr1 prefix="$STICK_CANARY_FLAP.0/24"
