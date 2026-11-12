#!/bin/bash
# Eight devices in three racks, each with an asset tag, eth0 and eth1, and an address on both. The seventh
# has this run's tag (two others have tags that contain it), so the first page of five devices doesn't show
# it; its eth0 carries a distractor address.
set -euo pipefail
source "$STICK_LIB/common.sh"
site=$(netbox_id "dcim/sites/?slug=stick-lab")
role=$(netbox_id "dcim/device-roles/?slug=host")
dtype=$(netbox_id "dcim/device-types/?slug=linux-host")
declare -A rack
for name in row-a "$STICK_CANARY_RACK" row-c; do
    rack[$name]=$(netbox_api POST dcim/racks/ \
        "{\"name\": \"$name\", \"site\": $site, \"status\": \"active\"}" | jq -r .id)
done
add_device() {  # <name> <asset tag> <rack name> <eth0 address> <eth1 address>
    local device id ifname addr
    device=$(netbox_api POST dcim/devices/ "$(jq -n --arg n "$1" --arg t "$2" --argjson s "$site" \
        --argjson r "$role" --argjson d "$dtype" --argjson k "${rack[$3]}" \
        '{name: $n, asset_tag: $t, site: $s, role: $r, device_type: $d, rack: $k, status: "active"}')" | jq -r .id)
    for ifname in eth0 eth1; do
        addr=$4
        [[ $ifname == eth1 ]] && addr=$5
        id=$(netbox_api POST dcim/interfaces/ \
            "{\"device\": $device, \"name\": \"$ifname\", \"type\": \"1000base-t\"}" | jq -r .id)
        netbox_api POST ipam/ip-addresses/ "{\"address\": \"$addr/24\", \"status\": \"active\",
            \"assigned_object_type\": \"dcim.interface\", \"assigned_object_id\": $id}" >/dev/null
    done
}
for n in 1 2 3 4 5 6; do
    tag="inv-000$n"
    [[ $n == 2 ]] && tag="${STICK_CANARY_TAG}-old"
    [[ $n == 5 ]] && tag="x-${STICK_CANARY_TAG}"
    which=row-a
    (( n % 2 )) || which=row-c
    add_device "node-0$n" "$tag" "$which" "192.0.2.$((10 + n))" "198.51.100.$((10 + n))"
done
add_device "$STICK_CANARY_DEVICE" "$STICK_CANARY_TAG" "$STICK_CANARY_RACK" 192.0.2.90 "$STICK_CANARY_ADDR"
add_device node-08 inv-0008 "$STICK_CANARY_RACK" 192.0.2.18 198.51.100.18
