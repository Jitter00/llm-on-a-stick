#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
group=$(zabbix_api hostgroup.get "$(jq -n --arg n "$STICK_CANARY_SITE" '{output: ["groupid"], filter: {name: [$n]}}')" \
    | jq -er '.[0].groupid')
now=$(date +%s)
zabbix_api maintenance.create "$(jq -n --arg n "$STICK_CANARY_WINDOW" --arg g "$group" --argjson t "$now" \
    '{name: $n, maintenance_type: 1, active_since: $t, active_till: ($t + 7200), groups: [{groupid: $g}],
      timeperiods: [{timeperiod_type: 0, start_date: $t, period: 7200}]}')" >/dev/null
