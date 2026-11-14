#!/bin/bash
# Three sessions drop and come back, some time apart:
#   - srl1's ethernet-1/1 is disabled and enabled again (admin state and operational state both fall);
#   - frr1 resets its session to srl2 a number of times that only this run knows, with no port going down.
#     A reset can be over before Prometheus looks, so the count is in the router's own counter;
#   - frr2 shuts its end of the link to srl2: srl2's ethernet-1/2 goes down while it stays enabled.
set -euo pipefail
source "$STICK_LIB/common.sh"
came_up() {  # <router> <neighbour>: how often the session has established since Prometheus was emptied
    local s="established_transitions{source=\"$1\", neighbor_peer_address=\"$2\"}"
    echo "max_over_time(${s}[15m]) - min_over_time(${s}[15m])"
}
telemetry_ready
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/1 admin-state disable"
sleep 12
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/1 admin-state enable"
prom_wait "$(came_up srl1 10.0.1.1)" 1
for i in $(seq 1 "$STICK_CANARY_RESETS"); do
    frr_cli "$STICK_NODE_FRR1" "clear bgp 10.0.2.0" >/dev/null
    prom_wait "$(came_up srl2 10.0.2.1)" "$i"
done
sleep 10
frr_conf "$STICK_NODE_FRR2" "interface eth2" "shutdown"
sleep 12
frr_conf "$STICK_NODE_FRR2" "interface eth2" "no shutdown"
prom_wait "$(came_up srl2 10.0.2.3)" 1
prom_wait 'count(session_state == 1)' 4
prom_wait 'count(resets(admin_state[15m]) > 0)' 1
prom_wait 'count(resets(oper_state[15m]) > 0)' 2
prom_wait "$(came_up srl1 10.0.1.3)" 0
