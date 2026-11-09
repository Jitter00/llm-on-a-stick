#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
librenms_api POST devices "$(jq -n --arg h "$STICK_NODE_SRL1_IP" --arg c "$STICK_CANARY_COMMUNITY" \
    '{hostname: $h, version: "v2c", community: $c}')" >/dev/null
