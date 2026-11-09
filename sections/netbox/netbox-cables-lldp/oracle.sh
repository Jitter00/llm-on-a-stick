#!/bin/bash
# srl1's LLDP neighbours on its data ports (not mgmt0) -> one NetBox cable each.
set -euo pipefail
source "$STICK_LIB/common.sh"
iface_id() { netbox_id "dcim/interfaces/?device=$1&name=$2"; }
srl_cli "$STICK_NODE_SRL1" "show system lldp neighbor" \
    | awk -F'|' '$2 ~ /ethernet-/ {gsub(/ /, "", $2); gsub(/ /, "", $4); gsub(/ /, "", $8); print $2, $4, $8}' \
    | while read -r local_port peer peer_port; do
        a=$(iface_id srl1 "$local_port")
        b=$(iface_id "$peer" "$peer_port")
        netbox_api POST dcim/cables/ "$(jq -n --argjson a "$a" --argjson b "$b" '{
            a_terminations: [{object_type: "dcim.interface", object_id: $a}],
            b_terminations: [{object_type: "dcim.interface", object_id: $b}], status: "connected"}')" >/dev/null
    done
