#!/bin/bash
# Reference solution: the session SuzieQ's BGP assertion still fails; on its router, the interface that had
# the other address of the neighbour's /31 in the history (its oldest address list), and its current address.
set -euo pipefail
source "$STICK_LIB/common.sh"
down=$(sq_api bgp assert result=fail | jq -ec 'first')
router=$(jq -r .hostname <<<"$down")
peer=$(jq -r .peer <<<"$down")
mine="${peer%.*}.$(( ${peer##*.} ^ 1 ))/31"
change=$(sq_api interface show hostname="$router" view=all | jq -ec --arg mine "$mine" '
    [.[] | select(.ipAddressList != null)] | group_by(.ifname) | map(sort_by(.timestamp))
    | map(select(.[0].ipAddressList | index($mine))) | first
    | {ifname: .[0].ifname, old: .[0].ipAddressList[0], new: .[-1].ipAddressList[0]}')
jq -n --argjson d "$down" --argjson c "$change" \
    '{router: $d.hostname, peer: $d.peer, interface: $c.ifname, old_address: $c.old, new_address: $c.new}' \
    > "$STICK_WORKSPACE/answer.json"
