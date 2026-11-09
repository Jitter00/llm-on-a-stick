#!/bin/bash
# srl2 in NetBox with this run's descriptions (they match the router) and one wrong address on ethernet-1/2.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_set "$STICK_NODE_SRL2" "set / interface ethernet-1/1 description ${STICK_CANARY_E11_DESC}"
srl_set "$STICK_NODE_SRL2" "set / interface ethernet-1/2 description ${STICK_CANARY_E12_DESC}"
site=$(netbox_id "dcim/sites/?slug=stick-lab")
role=$(netbox_id "dcim/device-roles/?slug=spine")
dtype=$(netbox_id "dcim/device-types/?slug=7220-ixr-d2l")
platform=$(netbox_id "dcim/platforms/?slug=srlinux")
device=$(netbox_api POST dcim/devices/ "$(jq -n --argjson s "$site" --argjson r "$role" --argjson t "$dtype" \
    --argjson p "$platform" '{name: "srl2", site: $s, role: $r, device_type: $t, platform: $p, status: "active"}')" \
    | jq -r .id)
add_interface() {  # <name> <description> <address>
    local id
    id=$(netbox_api POST dcim/interfaces/ "$(jq -n --argjson d "$device" --arg n "$1" --arg x "$2" \
        '{device: $d, name: $n, type: "25gbase-x-sfp28", description: $x}')" | jq -r .id)
    netbox_api POST ipam/ip-addresses/ "$(jq -n --arg a "$3" --argjson i "$id" \
        '{address: $a, status: "active", assigned_object_type: "dcim.interface", assigned_object_id: $i}')" >/dev/null
}
add_interface ethernet-1/1 "$STICK_CANARY_E11_DESC" 10.0.2.0/31
add_interface ethernet-1/2 "$STICK_CANARY_E12_DESC" "$STICK_CANARY_ADDR/31"  # the drift: srl2 has 10.0.2.2/31
