#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
group=$(zabbix_group_id Routers)
template=$(zabbix_api template.get '{"output": ["templateid"], "filter": {"host": ["Network Generic Device by SNMP"]}}' \
    | jq -er '.[0].templateid')
zabbix_api host.create "$(jq -n --arg h "$STICK_CANARY_NAME" --arg ip "$STICK_NODE_SRL1_IP" \
    --arg c "$STICK_CANARY_COMMUNITY" --arg g "$group" --arg t "$template" \
    '{host: $h, groups: [{groupid: $g}], templates: [{templateid: $t}],
      interfaces: [{type: 2, main: 1, useip: 1, ip: $ip, dns: "", port: "161",
                    details: {version: 2, bulk: 1, community: $c}}]}')" >/dev/null
