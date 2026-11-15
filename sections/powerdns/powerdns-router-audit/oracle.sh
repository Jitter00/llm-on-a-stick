#!/bin/bash
# Reference solution: each router's 198.18 loopback address against what DNS answers for its name; the record
# set is written where the two differ (which also enables a disabled record and creates a missing one).
set -euo pipefail
source "$STICK_LIB/common.sh"
live() {  # live <router name> <container>
    case $1 in
        frr*) frr_cli "$2" "show running-config" | sed -n 's|^ ip address \(198\.18\.[0-9.]*\)/32$|\1|p' ;;
        srl*) srl_cli "$2" "info flat interface lo0" | sed -n 's|.* address \(198\.18\.[0-9.]*\)/32$|\1|p' ;;
    esac
}
for node in SRL1 SRL2 FRR1 FRR2; do
    name=${node,,}; var="STICK_NODE_$node"
    now=$(live "$name" "${!var}")
    [[ "$(pdns_records stick.lab. "$name.stick.lab." A)" == "$now" ]] && continue
    pdns_rrset stick.lab. "$name.stick.lab." A 300 "$now"
done
