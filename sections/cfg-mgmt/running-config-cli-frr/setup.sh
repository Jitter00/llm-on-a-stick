#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR2" "interface eth3" "description ${STICK_CANARY_HOST_DESC}"
