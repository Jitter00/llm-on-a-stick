#!/bin/bash
# Reference solution: the description at each ref, and the files whose content differs between the two trees.
set -euo pipefail
source "$STICK_LIB/common.sh"
b="change/$STICK_CANARY_BRANCH"
desc() { gitea_file routers/frr1.conf "$1" | awk '/^interface eth3$/ {f = 1; next} f && /description/ {print $2; exit}'; }
tree() {  # path -> blob id, for the commit a branch points at
    local sha
    sha=$(gitea_api GET "repos/$GITEA_REPO/branches" | jq -er --arg b "$1" '.[] | select(.name == $b) | .commit.id')
    gitea_api GET "repos/$GITEA_REPO/git/trees/$sha?recursive=true" \
        | jq -c '[.tree[] | select(.type == "blob") | {key: .path, value: .sha}] | from_entries'
}
jq -n --arg m "$(desc main)" --arg br "$(desc "$b")" --argjson a "$(tree main)" --argjson b "$(tree "$b")" \
    '{main: $m, branch: $br, changed_files: [($a + $b) | keys[] | select($a[.] != $b[.])]}' \
    > "$STICK_WORKSPACE/answer.json"
