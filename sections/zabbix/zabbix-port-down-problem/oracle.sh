#!/bin/bash
# Reference solution: the two ends of the failed link are srl2's ethernet-1/2 (to frr2) and frr2's eth2 (the
# only FRR port that is down; frr1's eth2 is up); one trigger on both items.
set -euo pipefail
source "$STICK_LIB/common.sh"
key() {  # key <host> <item name text>
    zabbix_api item.get "$(jq -n --arg h "$1" --arg t "$2" '{host: $h, output: ["key_"], search: {name: $t}}')" \
        | jq -er '.[0].key_'
}
a="last(/$STICK_CANARY_N_SRL2/$(key "$STICK_CANARY_N_SRL2" "Interface ethernet-1/2(to frr2): Operational status"))=2"
b="last(/$STICK_CANARY_N_FRR2/$(key "$STICK_CANARY_N_FRR2" "Interface eth2(): Operational status"))=2"
zabbix_api trigger.create "$(jq -n --arg d "Link down $STICK_CANARY_TRIGGER" --arg e "$a or $b" \
    '{description: $d, expression: $e, priority: 4}')" >/dev/null
