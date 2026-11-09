#!/bin/bash
# frr1's LLDP neighbours on its data ports (not eth0, the management network) -> one NetBox cable each.
set -euo pipefail
source "$STICK_LIB/common.sh"
iface_id() { netbox_id "dcim/interfaces/?device=$1&name=$2"; }
docker exec "$STICK_NODE_FRR1" lldpcli -f json show neighbors \
    | jq -r '.lldp.interface[] | to_entries[] | select(.key != "eth0")
             | "\(.key) \(.value.chassis | keys[0]) \(.value.port.id.value)"' \
    | while read -r local_port peer peer_port; do
        a=$(iface_id frr1 "$local_port")
        b=$(iface_id "$peer" "$peer_port")
        netbox_api POST dcim/cables/ "$(jq -n --argjson a "$a" --argjson b "$b" '{
            a_terminations: [{object_type: "dcim.interface", object_id: $a}],
            b_terminations: [{object_type: "dcim.interface", object_id: $b}], status: "connected"}')" >/dev/null
    done
