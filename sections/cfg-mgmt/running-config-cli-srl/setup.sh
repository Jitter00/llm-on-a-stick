#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/2 description ${STICK_CANARY_PORT_DESC}"
