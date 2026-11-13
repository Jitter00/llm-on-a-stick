#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
device=$(netbox_api GET "dcim/devices/?asset_tag=$STICK_CANARY_TAG" | jq -er '.results[0]')
addr=$(netbox_api GET "ipam/ip-addresses/?device_id=$(jq -r .id <<<"$device")&interface=eth1" \
    | jq -er '.results[0].address')
jq -n --arg d "$(jq -r .name <<<"$device")" --arg r "$(jq -r .rack.name <<<"$device")" --arg a "$addr" \
    '{device: $d, rack: $r, address: $a}' > "$STICK_WORKSPACE/answer.json"
