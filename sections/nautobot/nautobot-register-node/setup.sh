#!/bin/bash
# This run's descriptions on frr2's links, so they have to be read off the router.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR2" "interface eth1" "description ${STICK_CANARY_ETH1_DESC}" \
    "interface eth2" "description ${STICK_CANARY_ETH2_DESC}"
