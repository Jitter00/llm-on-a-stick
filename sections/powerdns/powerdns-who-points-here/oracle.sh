#!/bin/bash
# Reference solution: every zone's records; the names whose A record is the address, then the names whose
# CNAME is one of those.
set -euo pipefail
source "$STICK_LIB/common.sh"
records=$(for zone in $(pdns_api GET zones | jq -r '.[].name'); do pdns_api GET "zones/$zone" | jq -c '.rrsets[]'; done)
jq -s --arg addr "$STICK_CANARY_ADDR" '
    [.[] | select(.type == "A" and any(.records[]; .content == $addr and (.disabled | not))) | .name] as $direct
    | $direct + [.[] | select(.type == "CNAME" and (.records[0].content | IN($direct[]))) | .name]
    | {names: map(rtrimstr("."))}' <<<"$records" > "$STICK_WORKSPACE/answer.json"
