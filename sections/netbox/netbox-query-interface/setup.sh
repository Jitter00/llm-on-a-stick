#!/bin/bash
# A device with four interfaces; only eth2 carries this run's description, and the address on it is this run's.
set -euo pipefail
source "$STICK_LIB/common.sh"
site=$(netbox_id "dcim/sites/?slug=stick-lab")
role=$(netbox_id "dcim/device-roles/?slug=host")
dtype=$(netbox_id "dcim/device-types/?slug=linux-host")
device=$(netbox_api POST dcim/devices/ \
    "{\"name\": \"$STICK_CANARY_DEVICE\", \"site\": $site, \"role\": $role, \"device_type\": $dtype, \"status\": \"active\"}" \
    | jq -r .id)
declare -A desc=([eth0]="management" [eth1]="uplink to the core" [eth2]="$STICK_CANARY_DESC" [eth3]="spare")
for ifname in eth0 eth1 eth2 eth3; do
    id=$(netbox_api POST dcim/interfaces/ \
        "{\"device\": $device, \"name\": \"$ifname\", \"type\": \"1000base-t\", \"description\": \"${desc[$ifname]}\"}" \
        | jq -r .id)
    case $ifname in
        eth1) addr="198.51.100.10/24" ;;  # a distractor
        eth2) addr="$STICK_CANARY_ADDR/24" ;;
        *) continue ;;
    esac
    netbox_api POST ipam/ip-addresses/ \
        "{\"address\": \"$addr\", \"status\": \"active\", \"assigned_object_type\": \"dcim.interface\", \"assigned_object_id\": $id}" \
        >/dev/null
done
