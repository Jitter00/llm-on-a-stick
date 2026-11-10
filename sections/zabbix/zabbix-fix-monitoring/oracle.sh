#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
down=$(zabbix_api host.get '{"output": ["hostid"], "selectInterfaces": ["available"], "selectMacros": ["hostmacroid", "macro"]}' \
    | jq -e '[.[] | select(.interfaces[0].available == "2")][0]')
macro=$(jq -er '.macros[] | select(.macro == "{$SNMP_COMMUNITY}") | .hostmacroid' <<<"$down")
zabbix_api usermacro.update "$(jq -n --arg id "$macro" --arg c "$STICK_CANARY_COMMUNITY" \
    '{hostmacroid: $id, value: $c}')" >/dev/null
