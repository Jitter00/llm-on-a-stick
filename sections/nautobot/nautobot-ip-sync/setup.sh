#!/bin/bash
# frr1 and frr2 in Nautobot with their interfaces, and this run's service address on each router's lo.
# stick-lab holds prefixes for every address except frr2's LAN (10.1.2.0/24, only in Global). Recorded in
# stick-lab: frr1's 10.255.0.11/32 on lo (right) and 10.0.1.1/31 on eth2 (it is on eth1). Global has an old
# copy of frr2's 10.0.2.3/31 and 10.1.2.1/24, which don't count for stick-lab.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR1" "interface lo" "ip address ${STICK_CANARY_SVC1}/32"
frr_conf "$STICK_NODE_FRR2" "interface lo" "ip address ${STICK_CANARY_SVC2}/32"

prefix() {  # <namespace> <prefix> <description>
    nautobot_api POST ipam/prefixes/ "$(jq -n --arg p "$2" --arg ns "$1" --arg d "$3" \
        '{prefix: $p, namespace: {name: $ns}, status: {name: "Active"}, type: "network", description: $d}')" >/dev/null
}
prefix stick-lab 10.0.1.0/24 "srl1 links"
prefix stick-lab 10.0.2.0/24 "srl2 links"
prefix stick-lab 10.255.0.0/24 "router loopbacks"
prefix stick-lab 10.1.1.0/24 "h1 LAN"
prefix stick-lab 198.18.0.0/15 "service addresses"
prefix Global 10.0.0.0/16 "router links (old lab)"
prefix Global 10.1.2.0/24 "h2 LAN (old lab)"

declare -A ifid
for router in frr1 frr2; do
    device=$(nautobot_api POST dcim/devices/ "$(jq -n --arg n "$router" '{name: $n, location: {name: "stick-lab"},
        role: {name: "Leaf"}, device_type: {model: "FRR container"}, platform: {name: "FRR"}, status: {name: "Active"}}')" \
        | jq -r .id)
    for ifname in lo eth0 eth1 eth2 eth3; do
        type=1000base-t
        [[ $ifname == lo ]] && type=virtual
        ifid[$router/$ifname]=$(nautobot_api POST dcim/interfaces/ "$(jq -n --arg d "$device" --arg n "$ifname" \
            --arg t "$type" '{device: $d, name: $n, type: $t, status: {name: "Active"}}')" | jq -r .id)
    done
done
address() {  # <namespace> <address> [<router/interface>]
    local ip
    ip=$(nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$2" --arg ns "$1" \
        '{address: $a, namespace: {name: $ns}, status: {name: "Active"}, type: "host"}')" | jq -r .id)
    if [[ -n "${3:-}" ]]; then
        nautobot_api POST ipam/ip-address-to-interface/ "$(jq -n --arg i "$ip" --arg f "${ifid[$3]}" \
            '{ip_address: $i, interface: $f}')" >/dev/null
    fi
}
address stick-lab 10.255.0.11/32 frr1/lo
address stick-lab 10.0.1.1/31 frr1/eth2
address Global 10.0.2.3/31
address Global 10.1.2.1/24
