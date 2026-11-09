#!/bin/bash
# Compare NetBox with srl2's flat running config, field by field.
set -euo pipefail
source "$STICK_LIB/common.sh"
config=$(srl_cli "$STICK_NODE_SRL2" "info flat")
diffs="[]"
while read -r iface; do
    nb_desc=$(netbox_api GET "dcim/interfaces/?device=srl2&name=$iface" | jq -r '.results[0].description')
    dev_desc=$(grep -E "^set / interface $iface description " <<<"$config" | sed -E 's/.* description "?([^"]*)"?$/\1/' || true)
    if [[ "$nb_desc" != "$dev_desc" ]]; then
        diffs=$(jq --arg i "$iface" --arg n "$nb_desc" --arg d "$dev_desc" \
            '. + [{interface: $i, field: "description", netbox: $n, device: $d}]' <<<"$diffs")
    fi
    nb_ip=$(netbox_api GET "ipam/ip-addresses/?device=srl2&interface=$iface" | jq -r '[.results[].address] | sort | join(",")')
    dev_ip=$(grep -E "^set / interface $iface subinterface [0-9]+ ipv4 address [0-9./]+$" <<<"$config" \
        | awk '{print $NF}' | sort | paste -sd, -)
    if [[ "$nb_ip" != "$dev_ip" ]]; then
        diffs=$(jq --arg i "$iface" --arg n "$nb_ip" --arg d "$dev_ip" \
            '. + [{interface: $i, field: "ipv4", netbox: $n, device: $d}]' <<<"$diffs")
    fi
done < <(netbox_api GET "dcim/interfaces/?device=srl2" | jq -r '.results[].name')
jq -n --argjson d "$diffs" '{differences: $d}' > "$STICK_WORKSPACE/answer.json"
