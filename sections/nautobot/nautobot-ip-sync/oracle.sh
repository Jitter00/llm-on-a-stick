#!/bin/bash
# Read every address on the two routers' lo, eth1-eth3; record each in stick-lab on its interface, moving a
# misassigned one and adding a missing prefix first.
set -euo pipefail
source "$STICK_LIB/common.sh"
for router in frr1 frr2; do
    container_var="STICK_NODE_${router^^}"
    frr_cli "${!container_var}" "show running-config" \
        | awk -v r="$router" '/^interface / {i=$2} /^ ip address / {print r, i, $3}'
done | while read -r router ifname address; do
    [[ $ifname =~ ^(lo|eth[123])$ ]] || continue
    iface=$(nautobot_id "dcim/interfaces/?device=$router&name=$ifname")
    existing=$(nautobot_api GET "ipam/ip-addresses/?address=$address&namespace=stick-lab" | jq -r '.results[0].id // empty')
    if [[ -n $existing ]]; then
        link=$(nautobot_api GET "ipam/ip-address-to-interface/?ip_address=$existing" | jq -r '.results[0] // empty')
        if [[ -n $link && $(jq -r .interface.id <<<"$link") != "$iface" ]]; then
            nautobot_api PATCH "ipam/ip-address-to-interface/$(jq -r .id <<<"$link")/" \
                "$(jq -n --arg f "$iface" '{interface: $f}')" >/dev/null
        fi
        continue
    fi
    network=$(python3 -c 'import ipaddress, sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "$address")
    holders=$(nautobot_api GET "ipam/prefixes/?contains=${address%/*}&namespace=stick-lab" | jq -r .count)
    if [[ $holders == 0 ]]; then
        nautobot_api POST ipam/prefixes/ "$(jq -n --arg p "$network" \
            '{prefix: $p, namespace: {name: "stick-lab"}, status: {name: "Active"}, type: "network"}')" >/dev/null
    fi
    ip=$(nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$address" \
        '{address: $a, namespace: {name: "stick-lab"}, status: {name: "Active"}, type: "host"}')" | jq -r .id)
    nautobot_api POST ipam/ip-address-to-interface/ "$(jq -n --arg i "$ip" --arg f "$iface" \
        '{ip_address: $i, interface: $f}')" >/dev/null
done
