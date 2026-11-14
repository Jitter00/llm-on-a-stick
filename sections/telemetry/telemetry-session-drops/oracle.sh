#!/bin/bash
# The port whose admin state fell; the port whose operational state fell while its admin state did not; for
# each, the session on that router that was down at the same scrape. The session left over is the one that
# was only reset: how often it came back is the growth of the router's established-transitions counter.
set -euo pipefail
source "$STICK_LIB/common.sh"
q() { curl -fsS -G "${STICK_TELEMETRY_URL%/}/api/v1/query" --data-urlencode "query=$1" | jq -c '.data.result'; }
with() {  # <router> <interface>: the neighbour whose session was down while that port was down
    prom_labels "max_over_time((session_state{source=\"$1\"} == bool 0 and on(source) (oper_state{source=\"$1\", interface_name=\"$2\"} == 0))[15m:5s]) > 0" neighbor_peer_address
}
dis=$(q 'resets(admin_state[15m]) > 0' | jq -c '.[0].metric')
fail=$(q 'resets(oper_state[15m]) > 0 unless resets(admin_state[15m]) > 0' | jq -c '.[0].metric')
dr=$(jq -r .source <<<"$dis"); di=$(jq -r .interface_name <<<"$dis")
fr=$(jq -r .source <<<"$fail"); fi_=$(jq -r .interface_name <<<"$fail")
dn=$(with "$dr" "$di"); fn=$(with "$fr" "$fi_")
grow='max_over_time(established_transitions[15m]) - min_over_time(established_transitions[15m])'
only=$(q "$grow > 0" | jq -c --arg a "$dn" --arg b "$fn" \
    '[.[] | select(.metric.neighbor_peer_address != $a and .metric.neighbor_peer_address != $b)][0]')
jq -n --arg dr "$dr" --arg di "$di" --arg dn "$dn" --arg fr "$fr" --arg fp "$fi_" --arg fn "$fn" \
    --arg sr "$(jq -r .metric.source <<<"$only")" --arg sn "$(jq -r .metric.neighbor_peer_address <<<"$only")" \
    --argjson t "$(jq -r '.value[1]' <<<"$only")" \
    '{port_disabled: {router: $dr, interface: $di, neighbor: $dn},
      link_failed: {router: $fr, interface: $fp, neighbor: $fn},
      session_only: {router: $sr, neighbor: $sn, times: $t}}' > "$STICK_WORKSPACE/answer.json"
