#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
iface=$(netbox_api GET "dcim/interfaces/?device=$STICK_CANARY_DEVICE&description=$STICK_CANARY_DESC" | jq -er '.results[0]')
id=$(jq -r .id <<<"$iface")
addr=$(netbox_api GET "ipam/ip-addresses/?interface_id=$id" | jq -er '.results[0].address')
jq -n --arg i "$(jq -r .name <<<"$iface")" --arg a "$addr" '{interface: $i, address: $a}' > "$STICK_WORKSPACE/answer.json"
