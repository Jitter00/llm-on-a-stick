#!/bin/bash
# Reference solution: the ticket's two commits on main, applied line by line to the release branch's files, on
# a new branch from the release branch, and one pull request into it.
set -euo pipefail
source "$STICK_LIB/common.sh"
rel=release/2026.11 br="backport/$STICK_CANARY_TICKET"
gitea_branch "$br" "$rel"
f1=$(gitea_file routers/frr1.conf "$rel")
f1=${f1/permit 10.1.1.0\/24 le 32/permit 10.1.1.0/24}
f1=${f1/ neighbor 10.0.2.0 remote-as 65002/ neighbor 10.0.2.0 remote-as 65002
 neighbor 10.0.1.0 password $STICK_CANARY_PW1}
printf '%s\n' "$f1" | gitea_commit "$br" routers/frr1.conf "Backport ticket $STICK_CANARY_TICKET to frr1" "Stick Oracle" 2026-09-20T09:00:00Z
f2=$(gitea_file routers/frr2.conf "$rel")
f2=${f2/ neighbor 10.0.2.2 remote-as 65002/ neighbor 10.0.2.2 remote-as 65002
 neighbor 10.0.2.2 password $STICK_CANARY_PW2}
printf '%s\n' "$f2" | gitea_commit "$br" routers/frr2.conf "Backport ticket $STICK_CANARY_TICKET to frr2" "Stick Oracle" 2026-09-20T09:05:00Z
gitea_api POST "repos/$GITEA_REPO/pulls" "$(jq -n --arg h "$br" --arg b "$rel" --arg t "Backport ticket $STICK_CANARY_TICKET" \
    '{head: $h, base: $b, title: $t, body: "The two commits of the ticket, applied to the release branch."}')" >/dev/null
