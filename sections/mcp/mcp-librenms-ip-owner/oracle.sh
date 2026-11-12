#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
all=$(librenms_api GET resources/ip/addresses)
port_id=$(jq -er --arg a "$STICK_CANARY_ADDR" '.ip_addresses[] | select(.ipv4_address == $a) | .port_id' <<<"$all")
port=$(librenms_api GET "ports/$port_id" | jq -e '.port[0]')
device=$(librenms_api GET "devices/$(jq -r .device_id <<<"$port")" | jq -er '.devices[0].sysName')
jq -n --arg d "$device" --arg p "$(jq -r .ifName <<<"$port")" --argjson id "$port_id" --argjson all "$all" \
    '{device: $d, port: $p,
      addresses: [$all.ip_addresses[] | select(.port_id == $id and .ipv4_address != null) | .ipv4_address]}' \
    > "$STICK_WORKSPACE/answer.json"
