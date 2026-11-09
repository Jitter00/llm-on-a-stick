#!/bin/bash
# NetBox lists the four routers under this run's random names, each with its real management address as
# primary IPv4: srl1, frr1 and frr2 active, srl2 planned. LibreNMS monitors frr2 only.
set -euo pipefail
source "$STICK_LIB/common.sh"
site=$(netbox_id "dcim/sites/?slug=stick-lab")
add_device() {  # <name> <address> <status> <role slug> <device type slug> <platform slug>
    local device iface addr
    device=$(netbox_api POST dcim/devices/ "$(jq -n --arg n "$1" --arg st "$3" --argjson s "$site" \
        --argjson r "$(netbox_id "dcim/device-roles/?slug=$4")" \
        --argjson t "$(netbox_id "dcim/device-types/?slug=$5")" \
        --argjson p "$(netbox_id "dcim/platforms/?slug=$6")" \
        '{name: $n, site: $s, role: $r, device_type: $t, platform: $p, status: $st}')" | jq -r .id)
    iface=$(netbox_api POST dcim/interfaces/ "$(jq -n --argjson d "$device" \
        '{device: $d, name: "mgmt0", type: "1000base-t", mgmt_only: true}')" | jq -r .id)
    addr=$(netbox_api POST ipam/ip-addresses/ "$(jq -n --arg a "$2/24" --argjson i "$iface" \
        '{address: $a, status: "active", assigned_object_type: "dcim.interface", assigned_object_id: $i}')" \
        | jq -r .id)
    netbox_api PATCH "dcim/devices/$device/" "$(jq -n --argjson a "$addr" '{primary_ip4: $a}')" >/dev/null
}
add_device "$STICK_CANARY_N1" "$STICK_NODE_SRL1_IP" active spine 7220-ixr-d2l srlinux
add_device "$STICK_CANARY_N2" "$STICK_NODE_SRL2_IP" planned spine 7220-ixr-d2l srlinux
add_device "$STICK_CANARY_N3" "$STICK_NODE_FRR1_IP" active leaf frr-container frr
add_device "$STICK_CANARY_N4" "$STICK_NODE_FRR2_IP" active leaf frr-container frr
librenms_add_device "$STICK_NODE_FRR2_IP" stick-ro
