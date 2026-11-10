#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
# The port's "Operational status" item whose last value is 2 (down): its host and key go in the expression.
item=$(zabbix_api item.get "$(jq -n --arg d "(${STICK_CANARY_DESC}): Operational status" \
    '{output: ["key_", "lastvalue"], selectHosts: ["host"], search: {name: $d}}')" \
    | jq -e '[.[] | select(.lastvalue == "2")][0]')
zabbix_api trigger.create "$(jq -n --arg n "$STICK_CANARY_TRIGGER" --argjson i "$item" \
    '{description: $n, priority: 4, expression: ("last(/" + $i.hosts[0].host + "/" + $i.key_ + ")=2")}')" >/dev/null
