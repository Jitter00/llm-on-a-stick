#!/bin/bash
# Reference solution: compare CLI (flat) with the Oxidized backup; NETCONF is read to confirm it matches the CLI.
# The sources go through temp files: a full NETCONF reply (~300 KB) is too big for an environment variable.
set -euo pipefail
source "$STICK_LIB/common.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
srl_cli "$STICK_NODE_SRL1" "info flat" > "$tmp/cli"
curl -sf "$OXIDIZED_URL/node/fetch/srl1" > "$tmp/backup"
netconf_get_config "$STICK_NODE_SRL1_IP" > "$tmp/netconf"

python3 - "$tmp" > "$STICK_WORKSPACE/answer.json" <<'PY'
import json, pathlib, re, sys
import xml.etree.ElementTree as ET

tmp = pathlib.Path(sys.argv[1])
def lines(name):
    return {" ".join(l.split()) for l in (tmp / name).read_text().splitlines() if l.strip()}

cli, backup = lines("cli"), lines("backup")
changed = sorted(cli ^ backup)

# NETCONF must agree with the CLI on every interface description.
root = ET.fromstring((tmp / "netconf").read_text().split("?>", 1)[-1])
for el in root.iter():
    el.tag = el.tag.split("}")[-1]
# Only top-level interfaces (directly under <data>): "interface" elements also appear under
# network-instances, LLDP etc., reusing the same names without a description.
netconf_desc = {i.findtext("name"): i.findtext("description") for i in root.find("data").findall("interface")}

answer = {"consistent": True, "outdated_source": "none", "interface": None, "device_description": None}
for line in changed:
    m = re.match(r"set / interface (\S+) description (.+)$", line)
    if m and line in cli:
        name, desc = m.group(1), m.group(2).strip('"')
        assert netconf_desc.get(name) == desc, "NETCONF disagrees with the CLI"
        answer = {"consistent": False, "outdated_source": "oxidized", "interface": name, "device_description": desc}
print(json.dumps(answer, indent=2))
PY
