#!/bin/bash
# Failed logins per source address (an aggregate over every router); the address with the most is the one
# to follow. Its successful login names the account and the session; that session's commit and commands
# give the router and the value.
set -euo pipefail
source "$STICK_LIB/common.sh"
failed='{job="syslog"} |= "Failed password for " | regexp " from (?P<src>[0-9.]+) port "'
by_source=$(curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" \
    --data-urlencode "query=sum by (src) (count_over_time($failed [15m]))" | jq -c '.data.result')
src=$(jq -r 'max_by(.value[1] | tonumber) | .metric.src' <<<"$by_source")
per_router=$(curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" \
    --data-urlencode "query=sum by (host) (count_over_time({job=\"syslog\"} |= \"Failed password for \" |= \" from $src port \" [15m]))" |
    jq -c '[.data.result[] | {(.metric.host): (.value[1] | tonumber)}] | add')
opened=$(loki_lines "{job=\"syslog\"} |= \"sessionOpened\" |= \"from host $src \"" | tail -1)
user=$(sed -n 's/.*Opened session [0-9]* for user \(\S*\) from host .*/\1/p' <<<"$opened")
session=$(sed -n 's/.*Opened session \([0-9]*\) for user .*/\1/p' <<<"$opened")
commit=$(loki_lines "{job=\"syslog\"} |= \"commitSucceeded\" |= \"by user $user session $session.\"" | tail -1)
router=$(curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" \
    --data-urlencode "query=sum by (host) (count_over_time({job=\"syslog\"} |= \"commitSucceeded\" |= \"by user $user session $session.\" [15m]))" |
    jq -er '.data.result[0].metric.host')
[[ -n "$commit" ]]
value=$(loki_lines "{host=\"$router\", app=\"sr_cli\"} |= \"|$user|$session|\" |= \"description\"" |
    sed -n 's/.* description \(\S*\).*/\1/p' | tail -1)
jq -n --arg s "$src" --argjson f "$per_router" --arg r "$router" --arg u "$user" --arg v "$value" \
    '{source: $s, failed_logins: $f, router: $r, user: $u, new_value: $v}' > "$STICK_WORKSPACE/answer.json"
