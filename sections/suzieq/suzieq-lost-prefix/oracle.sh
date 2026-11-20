#!/bin/bash
# Reference solution: the /24s frr1 had in its history but not now; then, in the history of the routers'
# addresses, the interface that had an address in that network.
set -euo pipefail
source "$STICK_LIB/common.sh"
now=$(sq_api route show hostname=frr1 prefixlen=24 | jq -c '[.[].prefix]')
prefix=$(sq_api route show hostname=frr1 prefixlen=24 view=all |
    jq -er --argjson now "$now" '[.[].prefix | select(. as $p | $now | index($p) | not)] | unique | .[0]')
net=${prefix%.0/24}
where=$(sq_api address show view=all | jq -ec --arg net "$net." \
    '[.[] | select(.ipAddressList | any(startswith($net)))] | first')
jq -n --arg p "$prefix" --argjson w "$where" '{prefix: $p, origin_router: $w.hostname, origin_interface: $w.ifname}' \
    > "$STICK_WORKSPACE/answer.json"
