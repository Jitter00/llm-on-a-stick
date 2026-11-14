#!/bin/bash
# Two instant queries: the ports whose admin state is "enable" (1), split by their operational state.
set -euo pipefail
source "$STICK_LIB/common.sh"
up=$(prom_value 'count(admin_state{source="srl2"} == 1 and oper_state{source="srl2"} == 1)')
down=$(prom_value 'count(admin_state{source="srl2"} == 1 and oper_state{source="srl2"} == 0)')
jq -n --argjson u "$up" --argjson d "$down" '{router: "srl2", enabled_and_up: $u, enabled_but_down: $d}' \
    > "$STICK_WORKSPACE/answer.json"
