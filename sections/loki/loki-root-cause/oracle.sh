#!/bin/bash
# Sessions that dropped "due to event CONFIG_CHG" name the router; the commit on it just before names the
# account and its session; that session's commands give the value, and its opening line the source address.
set -euo pipefail
source "$STICK_LIB/common.sh"
drops='{job="syslog"} |= "bgpNeighborBackwardTransition" |= "ESTABLISHED to lower state IDLE due to event CONFIG_CHG"'
router=$(curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" \
    --data-urlencode "query=sum by (host) (count_over_time($drops [15m]))" | jq -er '.data.result[0].metric.host')
peers=$(loki_lines "$drops" | sed -n 's/.*Peer \([0-9.]*\) moved.*/\1/p' | sort -u | jq -R . | jq -cs .)
commit=$(loki_lines "{host=\"$router\"} |= \"commitSucceeded\" != \"by user root \" != \"by user admin \"" | tail -1)
user=$(sed -n 's/.* by user \(\S*\) session .*/\1/p' <<<"$commit")
session=$(sed -n 's/.* session \([0-9]*\)\..*/\1/p' <<<"$commit")
value=$(loki_lines "{host=\"$router\", app=\"sr_cli\"} |= \"|$user|$session|\" |= \"router-id\"" |
    sed -n 's/.* router-id \(\S*\).*/\1/p' | tail -1)
source_ip=$(loki_lines "{host=\"$router\"} |= \"sessionOpened\" |= \"Opened session $session for user $user \"" |
    sed -n 's/.* from host \(\S*\) in .*/\1/p')
jq -n --arg r "$router" --arg u "$user" --arg s "$source_ip" --arg v "$value" --argjson p "$peers" \
    '{router: $r, user: $u, source: $s, new_value: $v, sessions_down: $p}' > "$STICK_WORKSPACE/answer.json"
