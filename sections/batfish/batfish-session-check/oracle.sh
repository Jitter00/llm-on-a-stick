#!/bin/bash
# Reference solution: the candidate's leaf sessions that aren't a unique match, each read against the spines.
# A neighbour address that no device owns is a wrong neighbour address: the right one is the spine address
# whose neighbour is one of this leaf's own addresses and which the leaf has no session to. Another session
# without a local address is a wrong own address: the right one is the neighbour the spine has for the leaf,
# with the spine's prefix length. A half-open session has a wrong AS: the one the leaf presents if the spine
# expects another, else the one it expects of the spine.
set -euo pipefail
source "$STICK_LIB/common.sh"
bf_py > "$STICK_WORKSPACE/answer.json" <<'PY'
import json
bf.set_snapshot("candidate")
compat = bf.q.bgpSessionCompatibility(nodes="/frr/").answer().frame()
spines = bf.q.bgpPeerConfiguration(nodes="/srl/").answer().frame()
owners = bf.q.ipOwners().answer().frame()
broken, fixes = [], []
for s in compat[compat.Configured_Status != "UNIQUE_MATCH"].itertuples():
    peer = str(s.Remote_IP)
    def add(problem, should_be):
        broken.append({"router": s.Node, "peer": peer, "problem": problem})
        fixes.append({"router": s.Node, "peer": peer, "should_be": should_be})
    if peer not in set(owners.IP):
        mine = set(owners[owners.Node == s.Node].IP)
        configured = set(compat[compat.Node == s.Node].Remote_IP.astype(str))
        add("peer_address", next(str(p.Local_IP) for p in spines.itertuples()
                                 if str(p.Remote_IP) in mine and str(p.Local_IP) not in configured))
        continue
    spine = spines[spines.Local_IP.astype(str) == peer].iloc[0]
    if s.Configured_Status == "NO_LOCAL_IP":
        mask = owners[owners.IP == peer].Mask.iloc[0]
        add("local_address", f"{spine.Remote_IP}/{mask}")
    elif str(spine.Remote_AS) != str(s.Local_AS):
        add("local_as", int(spine.Remote_AS))
    else:
        add("remote_as", int(spine.Local_AS))
print(json.dumps({"broken": broken, "fixes": fixes}))
PY
