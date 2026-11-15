#!/bin/bash
# Reference solution: each router's live description against its file; a branch with the corrected file and a
# pull request for the one that differs.
set -euo pipefail
source "$STICK_LIB/common.sh"
live() {  # live <router name> <container>
    # awk reads to the end: leaving at the first match can end vtysh with SIGPIPE, which pipefail reports.
    case $1 in
        frr*) frr_cli "$2" "show running-config" | awk '/^interface eth1$/ {f = 1; next} f && /description/ {print $2; f = 0}' ;;
        srl*) srl_cli "$2" "info flat interface ethernet-1/1 description" | awk '{print $NF}' | tr -d '"' ;;
    esac
}
for node in SRL1 SRL2 FRR1 FRR2; do
    name=${node,,}; var="STICK_NODE_$node"; path="intended/$name.yaml"
    now=$(live "$name" "${!var}"); text=$(gitea_file "$path")
    recorded=$(sed -n 's/^    description: //p' <<<"$text")
    [[ "$recorded" == "$now" ]] && continue
    gitea_branch "fix/$name-description"
    printf '%s\n' "${text/description: $recorded/description: $now}" \
        | gitea_commit "fix/$name-description" "$path" "$name: record the uplink description it runs" "Stick Oracle" 2026-09-20T09:00:00Z
    gitea_api POST "repos/$GITEA_REPO/pulls" "$(jq -n --arg h "fix/$name-description" --arg t "$name: record the uplink description it runs" \
        '{head: $h, base: "main", title: $t, body: "The router was changed by hand; this brings its file in line."}')" >/dev/null
done
