#!/bin/bash
# One "Failed password" line per attempt; the router is the stream's host label, the source is in the line.
set -euo pipefail
source "$STICK_LIB/common.sh"
query="{job=\"syslog\"} |= \"Failed password for invalid user $STICK_CANARY_USER from\""
host=$(curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" \
    --data-urlencode "query=sum by (host) (count_over_time($query [15m]))" | jq -er '.data.result[0].metric.host')
source_ip=$(loki_lines "$query" | sed -n 's/.* from \([0-9.]*\) port .*/\1/p' | sort -u)
jq -n --arg r "$host" --arg s "$source_ip" --argjson n "$(loki_count "$query")" \
    '{router: $r, source: $s, failed_attempts: $n}' > "$STICK_WORKSPACE/answer.json"
