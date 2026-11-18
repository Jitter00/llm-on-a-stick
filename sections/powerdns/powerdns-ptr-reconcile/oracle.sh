#!/bin/bash
# Reference solution: every enabled A record in the two forward zones whose address falls in a reverse zone
# here gives the PTR record that zone should hold; then each reverse zone gets exactly those (add, correct,
# delete).
set -euo pipefail
source "$STICK_LIB/common.sh"
want=$(for zone in stick.lab. oob.example.; do
    pdns_api GET "zones/$zone" | jq -r '.rrsets[] | select(.type == "A") | .name as $n
        | .records[] | select(.disabled | not) | "\(.content) \($n)"'
done)
for third in "$STICK_CANARY_T1" "$STICK_CANARY_T2"; do
    rev="$third.19.198.in-addr.arpa."
    declare -A should=()
    while read -r address name; do
        [[ $address == 198.19.$third.* ]] && should["${address##*.}.$rev"]+="$name "
    done <<<"$want"
    have=$(pdns_api GET "zones/$rev" | jq -r '.rrsets[] | select(.type == "PTR") | .name')
    for name in $have; do
        [[ -z "${should[$name]:-}" ]] && pdns_delete "$rev" "$name" PTR
    done
    for name in "${!should[@]}"; do
        read -ra targets <<<"${should[$name]}"
        pdns_rrset "$rev" "$name" PTR 3600 "${targets[@]}"
    done
    unset should
done
