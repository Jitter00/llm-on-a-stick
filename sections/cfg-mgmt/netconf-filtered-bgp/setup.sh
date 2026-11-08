#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL1" \
    "set / network-instance default protocols bgp neighbor 10.0.1.1 description ${STICK_CANARY_PEER_DESC}"
