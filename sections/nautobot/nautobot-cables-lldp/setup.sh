#!/bin/bash
# frr1's two SR Linux neighbours get this run's random host names, which they send as their LLDP system names,
# and are in Nautobot under those names: which neighbour sits on which frr1 port can only be learnt from LLDP.
# (The host names stay until the lab is redeployed; no other task depends on them.)
set -euo pipefail
source "$STICK_LIB/common.sh"

srl_set "$STICK_NODE_SRL1" "set / system name host-name ${STICK_CANARY_N1}"
srl_set "$STICK_NODE_SRL2" "set / system name host-name ${STICK_CANARY_N2}"
# SR Linux sends LLDP every 30 s: wait until frr1 has heard both new names.
seen=""
for _ in $(seq 1 30); do
    seen=$(docker exec "$STICK_NODE_FRR1" lldpcli show neighbors)
    if grep -q "$STICK_CANARY_N1" <<<"$seen" && grep -q "$STICK_CANARY_N2" <<<"$seen"; then break; fi
    sleep 2
done
if ! grep -q "$STICK_CANARY_N1" <<<"$seen" || ! grep -q "$STICK_CANARY_N2" <<<"$seen"; then
    echo "frr1 did not hear the new LLDP names within 60 s" >&2
    exit 1
fi

# Nautobot: the three devices and their interfaces (status is required on both), no cables.
add_device() {  # <name> <role> <device type> <platform> <interface type> <interfaces...>
    local name=$1 role=$2 type=$3 platform=$4 iftype=$5 device
    device=$(nautobot_api POST dcim/devices/ "$(jq -n --arg n "$name" --arg r "$role" --arg t "$type" \
        --arg p "$platform" '{name: $n, location: {name: "stick-lab"}, role: {name: $r}, device_type: {model: $t},
        platform: {name: $p}, status: {name: "Active"}}')" | jq -r .id)
    shift 5
    for ifname in "$@"; do
        nautobot_api POST dcim/interfaces/ "$(jq -n --arg d "$device" --arg n "$ifname" --arg t "$iftype" \
            '{device: $d, name: $n, type: $t, status: {name: "Active"}}')" >/dev/null
    done
}
add_device frr1 Leaf "FRR container" FRR 1000base-t eth0 eth1 eth2 eth3
add_device "$STICK_CANARY_N1" Spine "7220 IXR-D2L" "SR Linux" 25gbase-x-sfp28 mgmt0 ethernet-1/1 ethernet-1/2
add_device "$STICK_CANARY_N2" Spine "7220 IXR-D2L" "SR Linux" 25gbase-x-sfp28 mgmt0 ethernet-1/1 ethernet-1/2
