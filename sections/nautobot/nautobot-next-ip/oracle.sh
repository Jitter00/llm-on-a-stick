#!/bin/bash
# Nautobot's first available address in the stick-lab pool, recorded as a /32 in that namespace, linked to frr2's
# lo and configured there.
set -euo pipefail
source "$STICK_LIB/common.sh"
prefix=$(nautobot_id "ipam/prefixes/?prefix=$STICK_CANARY_POOL.0/24&namespace=stick-lab")
first=$(nautobot_api GET "ipam/prefixes/$prefix/available-ips/?limit=1" | jq -er '.[0].address')
address="${first%/*}/32"
lo=$(nautobot_id "dcim/interfaces/?device=frr2&name=lo")
ip=$(nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$address" \
    '{address: $a, namespace: {name: "stick-lab"}, status: {name: "Active"}, type: "host"}')" | jq -r .id)
nautobot_api POST ipam/ip-address-to-interface/ "{\"ip_address\": \"$ip\", \"interface\": \"$lo\"}" >/dev/null
frr_conf "$STICK_NODE_FRR2" "interface lo" "ip address $address"
