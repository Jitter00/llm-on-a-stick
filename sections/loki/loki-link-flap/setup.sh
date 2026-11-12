#!/bin/bash
# srl2's ethernet-1/1 (the link to frr1) goes down and up a number of times that only this run knows; the
# BGP session 10.0.2.0 - 10.0.2.1 drops each time. Around it: srl1's ethernet-1/1 (also to frr1) goes down
# once, and frr2 resets its session to srl1 with no link going down at all.
set -euo pipefail
source "$STICK_LIB/common.sh"
flap() {  # <container> <interface>: down, then up again and wait for the BGP session over it
    srl_set "$1" "set / interface $2 admin-state disable"
    sleep 2
    srl_set "$1" "set / interface $2 admin-state enable"
    sleep 6
}
flap "$STICK_NODE_SRL1" ethernet-1/1
half=$((STICK_CANARY_FLAPS / 2))
for _ in $(seq 1 "$half"); do flap "$STICK_NODE_SRL2" ethernet-1/1; done
frr_cli "$STICK_NODE_FRR2" "clear bgp 10.0.1.2" >/dev/null
for _ in $(seq 1 $((STICK_CANARY_FLAPS - half))); do flap "$STICK_NODE_SRL2" ethernet-1/1; done
loki_wait '{host="srl2"} |= "portDown" |= "Interface ethernet-1/1 is now down"' "$STICK_CANARY_FLAPS"
loki_wait '{host="srl1"} |= "portDown" |= "Interface ethernet-1/1 is now down"' 1
loki_wait '{host="frr2"} |= "ADJCHANGE: neighbor 10.0.1.2" |= "Down User reset"' 1
[[ "$(loki_count '{host="frr1"} |= "ADJCHANGE: neighbor 10.0.2.0" |= "Down"')" -ge 1 ]]
