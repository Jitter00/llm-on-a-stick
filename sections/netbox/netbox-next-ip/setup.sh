#!/bin/bash
# A loopback pool with .1, .2, .3 and .5 taken: the next free address is .4, not "the highest plus one".
# frr2 is in NetBox with its interfaces; the router itself starts from its boot config (stick task start).
set -euo pipefail
source "$STICK_LIB/common.sh"
pool=$STICK_CANARY_POOL

netbox_api POST ipam/prefixes/ "$(jq -n --arg p "$pool.0/24" \
    '{prefix: $p, status: "active", description: "loopbacks"}')" >/dev/null
for host in 1 2 3 5; do
    netbox_api POST ipam/ip-addresses/ "$(jq -n --arg a "$pool.$host/32" \
        '{address: $a, status: "active", description: "in use"}')" >/dev/null
done

site=$(netbox_id "dcim/sites/?slug=stick-lab")
role=$(netbox_id "dcim/device-roles/?slug=leaf")
dtype=$(netbox_id "dcim/device-types/?slug=frr-container")
platform=$(netbox_id "dcim/platforms/?slug=frr")
device=$(netbox_api POST dcim/devices/ "$(jq -n --argjson s "$site" --argjson r "$role" --argjson t "$dtype" \
    --argjson p "$platform" '{name: "frr2", site: $s, role: $r, device_type: $t, platform: $p, status: "active"}')" \
    | jq -r .id)
for ifname in lo eth0 eth1 eth2 eth3; do
    type=1000base-t
    [[ $ifname == lo ]] && type=virtual
    netbox_api POST dcim/interfaces/ "$(jq -n --argjson d "$device" --arg n "$ifname" --arg t "$type" \
        '{device: $d, name: $n, type: $t}')" >/dev/null
done
