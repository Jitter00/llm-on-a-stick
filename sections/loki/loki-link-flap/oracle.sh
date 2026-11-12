#!/bin/bash
# The port with the most portDown events; its neighbour from SR Linux's LLDP line for that port; the session
# from the peer SR Linux reports going down with it and the neighbour FRR reports at the same moments.
set -euo pipefail
source "$STICK_LIB/common.sh"
top=$(curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" --data-urlencode \
    'query=sort_desc(sum by (host, port) (count_over_time({job="syslog"} |= "|portDown|" | regexp "Interface (?P<port>\\S+) is now down" [15m])))' |
    jq -e '.data.result[0]')
router=$(jq -r .metric.host <<<"$top")
port=$(jq -r .metric.port <<<"$top")
neighbor=$(loki_lines "{host=\"$router\"} |= \"remotePeerRemoved\" |= \"interface $port:\"" |
    sed -n 's/.*: System \(\S*\) with chassis.*/\1/p' | sort -u)
far=$(loki_lines "{host=\"$router\"} |= \"bgpNeighborBackwardTransition\" |= \"ESTABLISHED\" != \"CONFIG\"" |
    sed -n 's/.*Peer \([0-9.]*\) moved.*/\1/p' | sort | uniq -c | sort -rn | awk 'NR==1 {print $2}')
near=$(loki_lines "{host=\"$neighbor\"} |= \"ADJCHANGE\" |= \"Down Interface down\"" |
    sed -n 's/.*neighbor \([0-9.]*\)(.*/\1/p' | sort | uniq -c | sort -rn | awk 'NR==1 {print $2}')
jq -n --arg r "$router" --arg p "$port" --arg n "$neighbor" --argjson t "$(jq -r '.value[1]' <<<"$top")" \
    --arg a "$near" --arg b "$far" \
    '{router: $r, interface: $p, neighbor: $n, times_down: $t, bgp_peers: [$a, $b]}' > "$STICK_WORKSPACE/answer.json"
