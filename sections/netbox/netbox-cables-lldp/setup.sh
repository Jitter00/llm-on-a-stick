#!/bin/bash
# frr1's two SR Linux neighbours get this run's random host names, which they send as their LLDP system names,
# and are in NetBox under those names: which neighbour sits on which frr1 port can only be learnt from LLDP.
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

# NetBox: the three devices and their interfaces, no cables.
site=$(netbox_id "dcim/sites/?slug=stick-lab")
add_device() {  # <name> <role> <type> <platform> <interface type> <interfaces...>
    local name=$1 role type platform iftype=$5 device
    role=$(netbox_id "dcim/device-roles/?slug=$2")
    type=$(netbox_id "dcim/device-types/?slug=$3")
    platform=$(netbox_id "dcim/platforms/?slug=$4")
    shift 5
    device=$(netbox_api POST dcim/devices/ "$(jq -n --arg n "$name" --argjson s "$site" --argjson r "$role" \
        --argjson t "$type" --argjson p "$platform" \
        '{name: $n, site: $s, role: $r, device_type: $t, platform: $p, status: "active"}')" | jq -r .id)
    for ifname in "$@"; do
        netbox_api POST dcim/interfaces/ "$(jq -n --argjson d "$device" --arg n "$ifname" --arg t "$iftype" \
            '{device: $d, name: $n, type: $t}')" >/dev/null
    done
}
add_device frr1 leaf frr-container frr 1000base-t eth0 eth1 eth2 eth3
add_device "$STICK_CANARY_N1" spine 7220-ixr-d2l srlinux 25gbase-x-sfp28 mgmt0 ethernet-1/1 ethernet-1/2
add_device "$STICK_CANARY_N2" spine 7220-ixr-d2l srlinux 25gbase-x-sfp28 mgmt0 ethernet-1/1 ethernet-1/2
