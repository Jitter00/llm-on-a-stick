#!/bin/bash
# A device with four interfaces; only eth2 carries this run's description, and the address on it is this run's.
# Addresses are linked to interfaces through ipam/ip-address-to-interface, so the interface list doesn't show them.
set -euo pipefail
source "$STICK_LIB/common.sh"
nautobot_api POST ipam/prefixes/ '{"prefix": "198.18.0.0/15", "namespace": {"name": "stick-lab"},
    "status": {"name": "Active"}, "type": "network", "description": "lab test networks"}' >/dev/null
nautobot_api POST ipam/prefixes/ '{"prefix": "198.51.100.0/24", "namespace": {"name": "stick-lab"},
    "status": {"name": "Active"}, "type": "network", "description": "uplinks"}' >/dev/null
device=$(nautobot_api POST dcim/devices/ "$(jq -n --arg n "$STICK_CANARY_DEVICE" '{name: $n,
    location: {name: "stick-lab"}, role: {name: "Host"}, device_type: {model: "Linux host"},
    status: {name: "Active"}}')" | jq -r .id)
declare -A desc=([eth0]="management" [eth1]="uplink to the core" [eth2]="$STICK_CANARY_DESC" [eth3]="spare")
for ifname in eth0 eth1 eth2 eth3; do
    id=$(nautobot_api POST dcim/interfaces/ "$(jq -n --arg d "$device" --arg n "$ifname" --arg x "${desc[$ifname]}" \
        '{device: $d, name: $n, type: "1000base-t", status: {name: "Active"}, description: $x}')" | jq -r .id)
    case $ifname in
        eth1) addr="198.51.100.10/24" ;;  # a distractor
        eth2) addr="$STICK_CANARY_ADDR/24" ;;
        *) continue ;;
    esac
    ip=$(nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$addr" \
        '{address: $a, namespace: {name: "stick-lab"}, status: {name: "Active"}, type: "host"}')" | jq -r .id)
    nautobot_api POST ipam/ip-address-to-interface/ "{\"ip_address\": \"$ip\", \"interface\": \"$id\"}" >/dev/null
done
