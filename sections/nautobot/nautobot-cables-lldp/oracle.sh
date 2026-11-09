#!/bin/bash
# frr1's LLDP neighbours on its data ports (not eth0, the management network) -> one Nautobot cable each, in
# Nautobot's termination_a/b form (not NetBox 4's a_terminations), status Connected.
set -euo pipefail
source "$STICK_LIB/common.sh"
iface_id() { nautobot_id "dcim/interfaces/?device=$1&name=$(jq -rn --arg n "$2" '$n|@uri')"; }
docker exec "$STICK_NODE_FRR1" lldpcli -f json show neighbors \
    | jq -r '.lldp.interface[] | to_entries[] | select(.key != "eth0")
             | "\(.key) \(.value.chassis | keys[0]) \(.value.port.id.value)"' \
    | while read -r local_port peer peer_port; do
        a=$(iface_id frr1 "$local_port")
        b=$(iface_id "$peer" "$peer_port")
        nautobot_api POST dcim/cables/ "$(jq -n --arg a "$a" --arg b "$b" '{
            termination_a_type: "dcim.interface", termination_a_id: $a,
            termination_b_type: "dcim.interface", termination_b_id: $b, status: {name: "Connected"}}')" >/dev/null
    done
