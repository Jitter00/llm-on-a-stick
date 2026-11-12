#!/bin/bash
# The /24 in the stick-lab namespace has its first, second and fourth /28 taken: the first free one is the
# third (.32/28), a hole, not "the one after the last". The same /24 also exists in the Global namespace
# (another lab's), with only its first /28 taken, so a lookup by prefix alone finds two parents.
set -euo pipefail
source "$STICK_LIB/common.sh"
pool=$STICK_CANARY_POOL
add_prefix() {  # <prefix> <namespace> <type> <description>
    nautobot_api POST ipam/prefixes/ "$(jq -n --arg p "$1" --arg ns "$2" --arg t "$3" --arg d "$4" \
        '{prefix: $p, namespace: {name: $ns}, status: {name: "Active"}, type: $t, description: $d}')" >/dev/null
}
add_prefix "$pool.0/24" Global container "customer blocks of another lab"
add_prefix "$pool.0/28" Global network "customer 1"
add_prefix "$pool.0/24" stick-lab container "customer blocks"
add_prefix "$pool.0/28" stick-lab network "customer 1"
add_prefix "$pool.16/28" stick-lab network "customer 2"
add_prefix "$pool.48/28" stick-lab network "customer 4"
