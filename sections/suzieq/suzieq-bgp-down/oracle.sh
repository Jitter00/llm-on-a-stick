#!/bin/bash
# Reference solution: the session SuzieQ's BGP assertion fails.
set -euo pipefail
source "$STICK_LIB/common.sh"
sq_api bgp assert result=fail |
    jq -e 'first | {router: .hostname, peer: .peer, peer_asn: .peerAsn}' > "$STICK_WORKSPACE/answer.json"
