#!/bin/bash
# Reference solution: each router's BGP section, turned into the answer's fields.
set -euo pipefail
source "$STICK_LIB/common.sh"
srl=$(srl_cli "$STICK_NODE_SRL2" "info flat network-instance default protocols bgp" | tr -d '"')
frr=$(frr_cli "$STICK_NODE_FRR1" "show running-config" | awk '/^router bgp/ {f=1} f {print} f && /^exit$/ {exit}')
srl_neighbor() {  # <address>
    jq -n --arg a "$1" \
        --argjson p "$(sed -n "s|^set / network-instance default protocols bgp neighbor $1 peer-as ||p" <<<"$srl")" \
        --arg d "$(sed -n "s|^set / network-instance default protocols bgp neighbor $1 description ||p" <<<"$srl")" \
        '{address: $a, peer_as: $p, description: $d}'
}
frr_neighbor() {  # <address>
    jq -n --arg a "$1" --argjson p "$(sed -n "s|^ neighbor $1 remote-as ||p" <<<"$frr")" \
        --arg d "$(sed -n "s|^ neighbor $1 description ||p" <<<"$frr")" '{address: $a, peer_as: $p, description: $d}'
}
jq -n --argjson sa "$(sed -n 's|^set / network-instance default protocols bgp autonomous-system ||p' <<<"$srl")" \
    --argjson fa "$(sed -n 's|^router bgp ||p' <<<"$frr")" \
    --argjson s1 "$(srl_neighbor 10.0.2.1)" --argjson s2 "$(srl_neighbor 10.0.2.3)" \
    --argjson f1 "$(frr_neighbor 10.0.1.0)" --argjson f2 "$(frr_neighbor 10.0.2.0)" \
    '{srl2: {asn: $sa, neighbors: [$s1, $s2]}, frr1: {asn: $fa, neighbors: [$f1, $f2]}}' \
    > "$STICK_WORKSPACE/answer.json"
