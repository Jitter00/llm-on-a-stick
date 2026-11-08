#!/bin/bash
# Reference solution: read the running config and BGP summary, build facts.json.
set -euo pipefail
source "$STICK_LIB/common.sh"
config=$(frr_cli "$STICK_NODE_FRR1" "show running-config")
bgp=$(frr_cli "$STICK_NODE_FRR1" "show bgp summary json")
CONFIG="$config" BGP="$bgp" python3 - > "$STICK_WORKSPACE/facts.json" <<'PY'
import json, os, re
config, bgp = os.environ["CONFIG"], json.loads(os.environ["BGP"])["ipv4Unicast"]
facts = {
    "hostname": re.search(r"^hostname (\S+)", config, re.M).group(1),
    "bgp_asn": bgp["as"],
    "router_id": bgp["routerId"],
    "bgp_neighbors": sorted(bgp["peers"]),
    "ipv4_addresses": re.findall(r"^\s*ip address (\S+)", config, re.M),
}
print(json.dumps(facts, indent=2))
PY
