#!/bin/bash
# Reference solution: eth3's block of the running configuration, as an SSH user sees it.
set -euo pipefail
source "$STICK_LIB/common.sh"
# awk reads to the end: leaving at the block's `exit` would break vtysh's pipe now and then (exit 141).
block=$(frr_cli "$STICK_NODE_FRR2" "show running-config" | awk '/^interface eth3$/ {f=1; next} f && /^exit/ {f=0} f')
jq -n --arg d "$(sed -n 's/^ description //p' <<<"$block")" --arg a "$(sed -n 's/^ ip address //p' <<<"$block")" \
    '{description: $d, ipv4: $a}' > "$STICK_WORKSPACE/answer.json"
