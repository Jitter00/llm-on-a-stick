#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
# The tenant's primary addresses in NetBox, then the Zabbix hosts whose interface has one of them.
ips=$(netbox_api GET "dcim/devices/?tenant=$STICK_CANARY_TENANT" \
    | jq -c '[.results[].primary_ip4.address | split("/")[0]]')
hosts=$(zabbix_api hostinterface.get "$(jq -n --argjson ips "$ips" '{output: ["hostid"], filter: {ip: $ips}}')" \
    | jq -c '[.[] | {hostid}] | unique')
now=$(date +%s)
zabbix_api maintenance.create "$(jq -n --arg n "$STICK_CANARY_WINDOW" --argjson h "$hosts" --argjson t "$now" \
    '{name: $n, maintenance_type: 0, active_since: $t, active_till: ($t + 7200), hosts: $h,
      timeperiods: [{timeperiod_type: 0, start_date: $t, period: 7200}]}')" >/dev/null
