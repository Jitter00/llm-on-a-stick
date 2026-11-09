#!/bin/bash
# The loopback pool in the stick-lab namespace has .1, .2, .3 and .5 taken: the next free address is .4, not
# "the highest plus one". The same /24 also exists in the Global namespace (another lab's pool, .1-.6 taken), so
# a lookup by prefix alone finds two pools.
# frr2 is in Nautobot with its interfaces; the router itself starts from its boot config (stick task start).
set -euo pipefail
source "$STICK_LIB/common.sh"
pool=$STICK_CANARY_POOL

add_pool() {  # <namespace> <description> <hosts...>
    local ns=$1 desc=$2
    nautobot_api POST ipam/prefixes/ "$(jq -n --arg p "$pool.0/24" --arg ns "$ns" --arg d "$desc" \
        '{prefix: $p, namespace: {name: $ns}, status: {name: "Active"}, type: "network", description: $d}')" >/dev/null
    shift 2
    for host in "$@"; do
        nautobot_api POST ipam/ip-addresses/ "$(jq -n --arg a "$pool.$host/32" --arg ns "$ns" \
            '{address: $a, namespace: {name: $ns}, status: {name: "Active"}, type: "host", description: "in use"}')" \
            >/dev/null
    done
}
add_pool Global "loopbacks of another lab" 1 2 3 4 5 6
add_pool stick-lab "loopbacks" 1 2 3 5

device=$(nautobot_api POST dcim/devices/ '{"name": "frr2", "location": {"name": "stick-lab"}, "role": {"name": "Leaf"},
    "device_type": {"model": "FRR container"}, "platform": {"name": "FRR"}, "status": {"name": "Active"}}' | jq -r .id)
for ifname in lo eth0 eth1 eth2 eth3; do
    type=1000base-t
    [[ $ifname == lo ]] && type=virtual
    nautobot_api POST dcim/interfaces/ "$(jq -n --arg d "$device" --arg n "$ifname" --arg t "$type" \
        '{device: $d, name: $n, type: $t, status: {name: "Active"}}')" >/dev/null
done
