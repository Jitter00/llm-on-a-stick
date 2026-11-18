#!/bin/bash
# Map NetBox's names to the routers by management address, pair the routers' interfaces by their /31 links,
# remove the cables that don't match, and add the missing ones.
set -euo pipefail
source "$STICK_LIB/common.sh"
declare -A name
for node in SRL1 SRL2 FRR1 FRR2; do
    ip_var="STICK_NODE_${node}_IP"
    name[$node]=$(netbox_api GET "dcim/devices/?q=&limit=100" | jq -r --arg a "${!ip_var}/24" \
        '.results[] | select(.primary_ip4.address == $a) | .name')
done
# Every point-to-point address on the routers: "<node> <interface> <address/len>".
links=$(
    for node in SRL1 SRL2; do
        container_var="STICK_NODE_${node}"
        srl_cli "${!container_var}" "info flat interface ethernet-1/* subinterface * ipv4 address *" \
            | awk -v n="$node" '/ipv4 address [0-9.]+\/31/ {print n, $4, $NF}'
    done
    for node in FRR1 FRR2; do
        container_var="STICK_NODE_${node}"
        frr_cli "${!container_var}" "show running-config" \
            | awk -v n="$node" '/^interface / {i=$2} /^ ip address [0-9.]+\/31/ {print n, i, $3}'
    done
)
# Pair addresses that share a /31.
want=$(python3 - "$links" <<'PY'
import ipaddress, sys
ends = {}
for line in sys.argv[1].splitlines():
    node, iface, addr = line.split()
    ends.setdefault(str(ipaddress.ip_interface(addr).network), []).append((node, iface))
for pair in ends.values():
    if len(pair) == 2:
        print(*pair[0], *pair[1])
PY
)
iface_id() { netbox_id "dcim/interfaces/?device=$1&name=$2"; }
# Remove cables whose ends aren't a wanted pair.
declare -A wanted
while read -r a ai b bi; do
    wanted["${name[$a]}/$ai ${name[$b]}/$bi"]=1
    wanted["${name[$b]}/$bi ${name[$a]}/$ai"]=1
done <<<"$want"
netbox_api GET "dcim/cables/?limit=100" | jq -r '.results[] | "\(.id) \(.a_terminations[0].object.device.name)/\(.a_terminations[0].object.name) \(.b_terminations[0].object.device.name)/\(.b_terminations[0].object.name)"' \
    | while read -r id a b; do
        [[ -n "${wanted["$a $b"]:-}" ]] || netbox_api DELETE "dcim/cables/$id/" >/dev/null
    done
while read -r a ai b bi; do
    aid=$(iface_id "${name[$a]}" "$ai")
    [[ $(netbox_api GET "dcim/interfaces/$aid/" | jq -r '.cable') == null ]] || continue
    netbox_api POST dcim/cables/ "$(jq -n --argjson a "$aid" --argjson b "$(iface_id "${name[$b]}" "$bi")" \
        '{a_terminations: [{object_type: "dcim.interface", object_id: $a}],
          b_terminations: [{object_type: "dcim.interface", object_id: $b}], status: "connected"}')" >/dev/null
done <<<"$want"
