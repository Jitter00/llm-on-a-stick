#!/bin/bash
# Per port, the highest 20-second rate in and out over the last ten minutes. The burst went through the router
# where a lot came in on one port and as much went out of another; its rate is its rate over the 20 s in the
# middle of the 30 s burst. (The ping flood comes in and goes out of the same port.)
set -euo pipefail
source "$STICK_LIB/common.sh"
peak() {  # <in|out>: "<router> <port> <Mbit/s>" per port
    curl -fsS -G "${STICK_TELEMETRY_URL%/}/api/v1/query" \
        --data-urlencode "query=max_over_time((rate(${1}_octets{interface_name=~\"ethernet-.*\"}[20s]) * 8 / 1e6)[10m:5s])" |
        jq -r '.data.result[] | "\(.metric.source) \(.metric.interface_name) \(.value[1])"'
}
ins=$(peak in); outs=$(peak out)
answer=$(jq -n --arg i "$ins" --arg o "$outs" '
    def rows($s): $s | split("\n") | map(select(. != "") | split(" ") | {router: .[0], port: .[1], mbps: (.[2] | tonumber)});
    [rows($i)[] as $in | rows($o)[] | select(.router == $in.router and .port != $in.port and .mbps > 5 and $in.mbps > 5)
     | {router, in_interface: $in.port, out_interface: .port, mbps: ((.mbps + $in.mbps) / 2 * 10 | round / 10)}]')
[[ $(jq length <<<"$answer") == 1 ]] || { echo "not one transit pair: $answer" >&2; exit 1; }
jq '.[0]' <<<"$answer" > "$STICK_WORKSPACE/answer.json"
