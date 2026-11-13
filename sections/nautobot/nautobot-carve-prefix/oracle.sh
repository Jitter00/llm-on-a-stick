#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
parent=$(nautobot_id "ipam/prefixes/?prefix=$STICK_CANARY_POOL.0/24&namespace=stick-lab")
# Nautobot lists the free space of a prefix in order; the first block may be larger than a /28.
first=$(nautobot_api GET "ipam/prefixes/$parent/available-prefixes/" | jq -er '.[0].prefix')
nautobot_api POST ipam/prefixes/ "$(jq -n --arg p "${first%/*}/28" --arg d "$STICK_CANARY_DESC" \
    '{prefix: $p, namespace: {name: "stick-lab"}, status: {name: "Reserved"}, type: "network", description: $d}')" \
    >/dev/null
