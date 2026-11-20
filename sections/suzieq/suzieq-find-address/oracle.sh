#!/bin/bash
# Reference solution: frr1's longest match for the host; the router where that prefix is a connected network,
# and its interface; frr1's LLDP neighbours on the route's outgoing interfaces are the spines.
set -euo pipefail
source "$STICK_LIB/common.sh"
route=$(sq_api route lpm hostname=frr1 address="$STICK_CANARY_NET.57" | jq -ec 'first')
prefix=$(jq -r .prefix <<<"$route")
where=$(sq_api route show prefix="$prefix" protocol=kernel | jq -ec 'first')
via=$(sq_api lldp show hostname=frr1 | jq -c --argjson oifs "$(jq -c .oifs <<<"$route")" \
    '[.[] | select(.ifname as $i | $oifs | index($i)) | .peerHostname] | unique')
jq -n --argjson w "$where" --argjson v "$via" '{router: $w.hostname, interface: $w.oifs[0], frr1_via: $v}' \
    > "$STICK_WORKSPACE/answer.json"
