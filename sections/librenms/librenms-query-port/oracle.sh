#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
port=$(librenms_api GET "ports?columns=device_id,ifName,ifAlias,ifIndex" \
    | jq -e --arg d "$STICK_CANARY_DESC" '.ports[] | select(.ifAlias == $d)')
device=$(librenms_api GET "devices/$(jq -r .device_id <<<"$port")" | jq -r '.devices[0].sysName')
jq --arg d "$device" '{device: $d, port: .ifName, ifindex: .ifIndex}' <<<"$port" > "$STICK_WORKSPACE/answer.json"
