#!/bin/bash
# Location $LOC holds two devices with this run's addresses (one interface without any); a third device with an
# address sits at stick-lab, so a query that isn't filtered by location returns it too.
set -euo pipefail
source "$STICK_LIB/common.sh"
nautobot_api POST ipam/prefixes/ '{"prefix": "198.18.0.0/15", "namespace": {"name": "stick-lab"},
    "status": {"name": "Active"}, "type": "network", "description": "lab test networks"}' >/dev/null
nautobot_api POST ipam/prefixes/ '{"prefix": "198.51.100.0/24", "namespace": {"name": "stick-lab"},
    "status": {"name": "Active"}, "type": "network", "description": "uplinks"}' >/dev/null
nautobot_api POST dcim/locations/ "$(jq -n --arg n "$STICK_CANARY_LOC" \
    '{name: $n, location_type: {name: "Site"}, status: {name: "Active"}}')" >/dev/null

add_device() {  # <name> <location> <interface>[=<address>]...
    local name=$1 loc=$2 device spec ifname addr id ip
    device=$(nautobot_api POST dcim/devices/ "$(jq -n --arg n "$name" --arg l "$loc" '{name: $n,
        location: {name: $l}, role: {name: "Leaf"}, device_type: {model: "FRR container"}, platform: {name: "FRR"},
        status: {name: "Active"}}')" | jq -r .id)
    shift 2
    for spec in "$@"; do
        ifname=${spec%%=*}
        addr=${spec#*=}
        id=$(nautobot_api POST dcim/interfaces/ "$(jq -n --arg d "$device" --arg n "$ifname" \
            '{device: $d, name: $n, type: "1000base-t", status: {name: "Active"}}')" | jq -r .id)
        [[ $addr == "$spec" ]] && continue
        ip=$(nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$addr" \
            '{address: $a, namespace: {name: "stick-lab"}, status: {name: "Active"}, type: "host"}')" | jq -r .id)
        nautobot_api POST ipam/ip-address-to-interface/ "{\"ip_address\": \"$ip\", \"interface\": \"$id\"}" >/dev/null
    done
}
add_device "$STICK_CANARY_D1" "$STICK_CANARY_LOC" eth0 "eth1=$STICK_CANARY_A1/24" "eth2=$STICK_CANARY_A2/24"
add_device "$STICK_CANARY_D2" "$STICK_CANARY_LOC" eth0 "eth1=$STICK_CANARY_A3/24"
add_device "$STICK_CANARY_DX" stick-lab eth0 "eth1=198.51.100.20/24"
