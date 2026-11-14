#!/bin/bash
# srl2's ethernet-1/1 (the link to frr1) goes down and up a number of times that only this run knows, each
# time for long enough that Prometheus sees it. Around it: srl1's ethernet-1/2 goes down once, and frr2
# resets its session to srl1 with no port going down. At the end everything is up again.
set -euo pipefail
source "$STICK_LIB/common.sh"
flap() {  # <container> <interface>: down for two scrapes, then up again for two
    srl_set "$1" "set / interface $2 admin-state disable"
    sleep 8
    srl_set "$1" "set / interface $2 admin-state enable"
    sleep 9
}
telemetry_ready
flap "$STICK_NODE_SRL1" ethernet-1/2
half=$((STICK_CANARY_FLAPS / 2))
for _ in $(seq 1 "$half"); do flap "$STICK_NODE_SRL2" ethernet-1/1; done
frr_cli "$STICK_NODE_FRR2" "clear bgp 10.0.1.2" >/dev/null
for _ in $(seq 1 $((STICK_CANARY_FLAPS - half))); do flap "$STICK_NODE_SRL2" ethernet-1/1; done
prom_wait 'count(session_state == 1)' 4
prom_wait 'resets(oper_state{source="srl2", interface_name="ethernet-1/1"}[15m])' "$STICK_CANARY_FLAPS"
prom_wait 'resets(oper_state{source="srl1", interface_name="ethernet-1/2"}[15m])' 1
prom_wait 'count(resets(session_state{source="srl2"}[15m]) > 0)' 1
