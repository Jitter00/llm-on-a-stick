#!/bin/bash
# Reference solution: both leaves' BGP routes in the candidate against the current snapshot. A network is lost
# or gained when every one of its routes is only on one side, and has fewer paths when some of its routes are
# only in the current snapshot and others are in both. The request is met if frr2 loses the test network.
# A gained network loops if a traceroute from frr2 to an address in it ends in a loop.
set -euo pipefail
source "$STICK_LIB/common.sh"
bf_py > "$STICK_WORKSPACE/answer.json" <<PY
import json
from pybatfish.datamodel import HeaderConstraints
diff = bf.q.routes(nodes="/frr/", protocols="bgp").answer(snapshot="candidate", reference_snapshot="current").frame()
by_net = diff.groupby(["Node", "Network"]).Entry_Presence.agg(set)
def nets(node, presence):
    return sorted(net for (n, net), p in by_net.items() if n == node and p == presence)
answer = {
    "frr2_loses": nets("frr2", {"Only in Reference"}),
    "frr2_gains": nets("frr2", {"Only in Snapshot"}),
    "frr2_fewer_paths": nets("frr2", {"Only in Reference", "Unchanged"}),
    "frr1_loses": nets("frr1", {"Only in Reference"}),
    "frr1_fewer_paths": nets("frr1", {"Only in Reference", "Unchanged"}),
}
def loops(net):
    to = HeaderConstraints(dstIps=net.replace(".0/24", ".1"))
    rows = bf.q.traceroute(startLocation="frr2", headers=to).answer(snapshot="candidate").frame()
    return any(trace.disposition == "LOOP" for trace in rows.Traces[0])
answer["frr2_loops"] = [net for net in answer["frr2_gains"] if loops(net)]
answer["request_met"] = "$STICK_CANARY_TEST.0/24" in answer["frr2_loses"]
print(json.dumps(answer))
PY
