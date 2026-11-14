#!/bin/bash
# The port whose operational state fell most often in the last 15 minutes, and the one session on that
# router that fell in the same minutes.
set -euo pipefail
source "$STICK_LIB/common.sh"
top=$(curl -fsS -G "${STICK_TELEMETRY_URL%/}/api/v1/query" --data-urlencode \
    'query=topk(1, resets(oper_state[15m]))' | jq -e '.data.result[0]')
router=$(jq -r .metric.source <<<"$top")
neighbor=$(prom_labels "resets(session_state{source=\"$router\"}[15m]) > 0" neighbor_peer_address)
jq -n --arg r "$router" --arg p "$(jq -r .metric.interface_name <<<"$top")" \
    --argjson t "$(jq -r '.value[1]' <<<"$top")" --arg n "$neighbor" \
    '{router: $r, interface: $p, times_down: $t, bgp_neighbor: $n}' > "$STICK_WORKSPACE/answer.json"
