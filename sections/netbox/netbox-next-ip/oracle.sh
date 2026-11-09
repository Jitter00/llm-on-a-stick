#!/bin/bash
# NetBox's first available address in the pool (with the prefix's /24), recorded as a /32 on frr2's lo and
# configured there.
set -euo pipefail
source "$STICK_LIB/common.sh"
prefix=$(netbox_id "ipam/prefixes/?prefix=$STICK_CANARY_POOL.0/24")
first=$(netbox_api GET "ipam/prefixes/$prefix/available-ips/?limit=1" | jq -er '.[0].address')
address="${first%/*}/32"
lo=$(netbox_id "dcim/interfaces/?device=frr2&name=lo")
netbox_api POST ipam/ip-addresses/ "$(jq -n --arg a "$address" --argjson i "$lo" \
    '{address: $a, status: "active", assigned_object_type: "dcim.interface", assigned_object_id: $i}')" >/dev/null
frr_conf "$STICK_NODE_FRR2" "interface lo" "ip address $address"
