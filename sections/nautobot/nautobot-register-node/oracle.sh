#!/bin/bash
# Device -> interfaces (status required) -> IP address in the stick-lab namespace -> linked to eth0 through
# ipam/ip-address-to-interface -> primary IPv4 (only once it is linked).
set -euo pipefail
source "$STICK_LIB/common.sh"
device=$(nautobot_api POST dcim/devices/ '{"name": "frr2", "location": {"name": "stick-lab"}, "role": {"name": "Leaf"},
    "device_type": {"model": "FRR container"}, "platform": {"name": "FRR"}, "status": {"name": "Active"}}' | jq -r .id)
config=$(frr_cli "$STICK_NODE_FRR2" "show running-config")
for ifname in eth0 eth1 eth2 eth3; do
    desc=$(awk -v i="interface $ifname" '$0 == i {f=1; next} f && /^ description / {sub(/^ description /, ""); print; exit}
        f && /^(exit|!)/ {exit}' <<<"$config")
    id=$(nautobot_api POST dcim/interfaces/ "$(jq -n --arg d "$device" --arg n "$ifname" --arg x "$desc" \
        '{device: $d, name: $n, type: "1000base-t", status: {name: "Active"}, description: $x}')" | jq -r .id)
    [[ $ifname == eth0 ]] && eth0=$id
done
ip=$(nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$STICK_NODE_FRR2_IP/24" \
    '{address: $a, namespace: {name: "stick-lab"}, status: {name: "Active"}, type: "host"}')" | jq -r .id)
nautobot_api POST ipam/ip-address-to-interface/ "{\"ip_address\": \"$ip\", \"interface\": \"$eth0\"}" >/dev/null
nautobot_api PATCH "dcim/devices/$device/" "{\"primary_ip4\": \"$ip\"}" >/dev/null
