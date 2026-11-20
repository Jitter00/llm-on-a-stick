#!/bin/bash
# Reference solution: for each window, a fork of the snapshot with the spine (or the two interfaces)
# deactivated; a traceroute from each leaf to the .1 of each of the other leaf's 198.19 /24s, now and in the
# fork. Lost: delivered now, not delivered in the fork.
set -euo pipefail
source "$STICK_LIB/common.sh"
bf_py > "$STICK_WORKSPACE/answer.json" <<'PY'
import json
from pybatfish.datamodel import HeaderConstraints, Interface
owners = bf.q.ipOwners().answer(snapshot="current").frame()
tests = owners[owners.IP.str.startswith("198.19.") & (owners.Mask == 24) & owners.Node.str.startswith("frr")]
other = {"frr1": "frr2", "frr2": "frr1"}
def reached(snapshot):
    """(leaf, network) for each of the other leaf's test networks whose .1 a packet from the leaf gets to."""
    found = set()
    for t in tests.itertuples():
        leaf = other[t.Node]
        rows = bf.q.traceroute(startLocation=leaf, headers=HeaderConstraints(dstIps=t.IP)).answer(snapshot=snapshot)
        if all(trace.disposition == "ACCEPTED" for trace in rows.frame().Traces[0]):
            found.add((leaf, t.IP.rsplit(".", 1)[0] + ".0/24"))
    return found
windows = {
    "srl1_down": {"deactivate_nodes": ["srl1"]},
    "srl2_down": {"deactivate_nodes": ["srl2"]},
    "links_cut": {"deactivate_interfaces": [Interface(hostname="frr1", interface="eth1"),
                                            Interface(hostname="frr2", interface="eth2")]},
}
now, answer = reached("current"), {}
for name, failure in windows.items():
    bf.fork_snapshot("current", name=name, overwrite=True, **failure)
    lost = now - reached(name)
    answer[name] = {f"{leaf}_loses": sorted(n for node, n in lost if node == leaf) for leaf in ("frr1", "frr2")}
print(json.dumps(answer))
PY
