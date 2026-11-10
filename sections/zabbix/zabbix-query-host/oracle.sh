#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
zabbix_api host.get "$(jq -n --arg v "$STICK_CANARY_CIRCUIT" \
    '{output: ["host"], selectInterfaces: ["ip", "type"], tags: [{tag: "circuit", value: $v, operator: 1}]}')" \
    | jq -e '.[0] | {host, ip: ([.interfaces[] | select(.type == "2")][0].ip)}' > "$STICK_WORKSPACE/answer.json"
