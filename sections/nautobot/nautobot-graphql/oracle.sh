#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
cat > "$STICK_WORKSPACE/query.graphql" <<GRAPHQL
{
  devices(location: "$STICK_CANARY_LOC") {
    name
    interfaces { name ip_addresses { address } }
  }
}
GRAPHQL
jq -Rs '{query: .}' "$STICK_WORKSPACE/query.graphql" \
    | curl -sf -X POST -H "Authorization: $STICK_NAUTOBOT_AUTH" -H "Content-Type: application/json" \
        --data @- "$STICK_NAUTOBOT_URL/api/graphql/" \
    | jq '{addresses: [.data.devices[] | .name as $d | .interfaces[] | .name as $i
                      | .ip_addresses[] | {device: $d, interface: $i, address: .address}]}' \
    > "$STICK_WORKSPACE/answer.json"
