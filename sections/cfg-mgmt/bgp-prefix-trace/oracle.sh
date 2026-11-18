#!/bin/bash
# Reference solution: srl2 has the prefix (its next hop from its route table); srl1 doesn't, because of the
# route-map frr1 applies out towards srl1; frr2 doesn't, because of the export policy srl2 applies to frr2.
# The names come from the configurations; whether they really match the prefix was settled by the setup.
set -euo pipefail
source "$STICK_LIB/common.sh"
prefix="${STICK_CANARY_POOL}.${STICK_CANARY_HOST}/32"
next_hop=$(srl_cli "$STICK_NODE_SRL2" "show network-instance default protocols bgp routes ipv4 prefix ${prefix}" |
    sed -n 's/^ *BGP next-hop *: *\([0-9.]*\).*/\1/p' | head -1)
frr_rm=$(frr_cli "$STICK_NODE_FRR1" "show running-config bgpd" |
    sed -n 's/^ *neighbor 10\.0\.1\.0 route-map \([^ ]*\) out$/\1/p')
srl_pol=$(srl_cli "$STICK_NODE_SRL2" "info flat network-instance default protocols bgp neighbor 10.0.2.3 export-policy" |
    sed -n 's/.*export-policy \[ *\([^ ]*\) *\]$/\1/p')
jq -n --arg nh "$next_hop" --arg rm "$frr_rm" --arg pol "$srl_pol" '{routers: [
    {router: "srl1", has_route: false, next_hop: null, filtered_by: {router: "frr1", policy: $rm, direction: "out"}},
    {router: "srl2", has_route: true, next_hop: $nh, filtered_by: null},
    {router: "frr2", has_route: false, next_hop: null, filtered_by: {router: "srl2", policy: $pol, direction: "out"}}
]}' > "$STICK_WORKSPACE/answer.json"
