#!/bin/bash
# Device -> interfaces -> IP address on eth0 -> primary IPv4 (the address must be assigned first).
set -euo pipefail
source "$STICK_LIB/common.sh"
site=$(netbox_id "dcim/sites/?slug=stick-lab")
role=$(netbox_id "dcim/device-roles/?slug=leaf")
dtype=$(netbox_id "dcim/device-types/?slug=frr-container")
platform=$(netbox_id "dcim/platforms/?slug=frr")
device=$(netbox_api POST dcim/devices/ "$(jq -n --argjson s "$site" --argjson r "$role" --argjson t "$dtype" \
    --argjson p "$platform" '{name: "frr2", site: $s, role: $r, device_type: $t, platform: $p, status: "active"}')" \
    | jq -r .id)
config=$(frr_cli "$STICK_NODE_FRR2" "show running-config")
for ifname in eth0 eth1 eth2 eth3; do
    desc=$(awk -v i="interface $ifname" '$0 == i {f=1; next} f && /^ description / {sub(/^ description /, ""); print; exit}
        f && /^(exit|!)/ {exit}' <<<"$config")
    id=$(netbox_api POST dcim/interfaces/ "$(jq -n --argjson d "$device" --arg n "$ifname" --arg x "$desc" \
        '{device: $d, name: $n, type: "1000base-t", description: $x}')" | jq -r .id)
    [[ $ifname == eth0 ]] && eth0=$id
done
ip=$(netbox_api POST ipam/ip-addresses/ "$(jq -n --arg a "$STICK_NODE_FRR2_IP/24" --argjson i "$eth0" \
    '{address: $a, status: "active", assigned_object_type: "dcim.interface", assigned_object_id: $i}')" | jq -r .id)
netbox_api PATCH "dcim/devices/$device/" "{\"primary_ip4\": $ip}" >/dev/null
