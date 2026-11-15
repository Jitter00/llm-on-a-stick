#!/bin/bash
# Reference solution: of the commits that touch the file, the one whose diff takes the neighbour's line out.
set -euo pipefail
source "$STICK_LIB/common.sh"
for sha in $(gitea_api GET "repos/$GITEA_REPO/commits?path=routers/frr2.conf&limit=50" | jq -r '.[].sha'); do
    diff=$(gitea_api GET "repos/$GITEA_REPO/git/commits/$sha.diff")
    grep -q "^- *neighbor $STICK_CANARY_GONE " <<<"$diff" || continue
    gitea_api GET "repos/$GITEA_REPO/git/commits/$sha" \
        | jq '{ticket: (.commit.message | capture("ticket (?<t>[^)]+)").t), author: .commit.author.name}' \
        > "$STICK_WORKSPACE/answer.json"
    exit 0
done
echo "no commit removes neighbor $STICK_CANARY_GONE" >&2; exit 1
