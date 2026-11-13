#!/bin/bash
# Reference solution: every router's own AS and the address of each of its interfaces, then every neighbour
# statement compared with the AS of the router that owns the neighbour's address.
set -euo pipefail
source "$STICK_LIB/common.sh"
declare -A own_as owner
neighbours=()  # "<router> <neighbour> <configured as>"
for node in SRL1 SRL2; do
    name=${node,,}; var="STICK_NODE_$node"; config=$(srl_cli "${!var}" "info flat")
    own_as[$name]=$(sed -n 's|^set / network-instance default protocols bgp autonomous-system ||p' <<<"$config")
    while read -r address; do owner[${address%/*}]=$name; done \
        < <(sed -n 's|^set / interface .* ipv4 address \([0-9./]*\).*|\1|p' <<<"$config")
    while read -r neighbour as; do neighbours+=("$name $neighbour $as"); done \
        < <(sed -n 's|^set / network-instance default protocols bgp neighbor \([0-9.]*\) peer-as \([0-9]*\)|\1 \2|p' <<<"$config")
done
for node in FRR1 FRR2; do
    name=${node,,}; var="STICK_NODE_$node"; config=$(frr_cli "${!var}" "show running-config")
    own_as[$name]=$(sed -n 's|^router bgp ||p' <<<"$config")
    while read -r address; do owner[${address%/*}]=$name; done < <(sed -n 's|^ ip address ||p' <<<"$config")
    while read -r neighbour as; do neighbours+=("$name $neighbour $as"); done \
        < <(sed -n 's|^ neighbor \([0-9.]*\) remote-as \([0-9]*\)|\1 \2|p' <<<"$config")
done
for entry in "${neighbours[@]}"; do
    read -r router neighbour configured <<<"$entry"
    actual=${own_as[${owner[$neighbour]}]}
    [[ $configured == "$actual" ]] ||
        jq -n --arg r "$router" --arg n "$neighbour" --argjson c "$configured" --argjson a "$actual" \
            '{router: $r, neighbor: $n, configured_as: $c, actual_as: $a}'
done | jq -s '{mismatches: .}' > "$STICK_WORKSPACE/answer.json"
