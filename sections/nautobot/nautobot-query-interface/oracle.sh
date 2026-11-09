#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
iface=$(nautobot_api GET "dcim/interfaces/?device=$STICK_CANARY_DEVICE&description=$(jq -rn --arg d "$STICK_CANARY_DESC" '$d|@uri')" \
    | jq -er '.results[0]')
id=$(jq -r .id <<<"$iface")
addr=$(nautobot_api GET "ipam/ip-addresses/?interfaces=$id" | jq -er '.results[0].address')
jq -n --arg i "$(jq -r .name <<<"$iface")" --arg a "$addr" '{interface: $i, address: $a}' > "$STICK_WORKSPACE/answer.json"
