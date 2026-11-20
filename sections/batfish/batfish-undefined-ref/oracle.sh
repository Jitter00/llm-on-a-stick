#!/bin/bash
# Reference solution: Batfish's undefined prefix-list reference gives the file and line; the route-map entry
# whose lines include that line is the one that refers to it; the BGP peer that has the route-map as its
# import or export policy is where it is applied.
set -euo pipefail
source "$STICK_LIB/common.sh"
bf_py > "$STICK_WORKSPACE/answer.json" <<'PY'
import json
bf.set_snapshot("current")
refs = bf.q.undefinedReferences().answer().frame()
ref = refs[refs.Struct_Type == "ip prefix-list"].iloc[0]
node = ref.File_Name.removeprefix("configs/").removesuffix(".cfg")
line = ref.Lines.lines[0]
entries = bf.q.definedStructures(nodes=node, types="route-map entry").answer().frame()
rmap, entry = next(e.Structure_Name for e in entries.itertuples() if line in e.Source_Lines.lines).rsplit(" ", 1)
peers = bf.q.bgpPeerConfiguration(nodes=node).answer().frame()
peer, direction = next(
    (str(p.Remote_IP), d) for p in peers.itertuples()
    for d, policies in (("in", p.Import_Policy), ("out", p.Export_Policy)) if rmap in policies
)
print(json.dumps({"router": node, "route_map": rmap, "entry": int(entry), "missing": ref.Ref_Name,
                  "peer": peer, "direction": direction}))
PY
