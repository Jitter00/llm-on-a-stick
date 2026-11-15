#!/bin/bash
# Reference solution: the record set is replaced as a whole, so the old address goes in again with the new
# one; then the PTR record in the reverse zone.
set -euo pipefail
source "$STICK_LIB/common.sh"
name="$STICK_CANARY_SVC.stick.lab."
rev="$STICK_CANARY_THIRD.19.198.in-addr.arpa."
ttl=$(pdns_api GET "zones/stick.lab.?rrset_name=$name&rrset_type=A" | jq '.rrsets[0].ttl')
mapfile -t now < <(pdns_records stick.lab. "$name" A)
pdns_rrset stick.lab. "$name" A "$ttl" "${now[@]}" "198.19.$STICK_CANARY_THIRD.$STICK_CANARY_HOST"
pdns_rrset "$rev" "$STICK_CANARY_HOST.$rev" PTR 3600 "$name"
