#!/bin/bash
# The four routers in NetBox under this run's names (n1 = srl1, n2 = srl2, n3 = frr1, n4 = frr2), each with its
# management address as primary IPv4, and their interfaces. Two cables: srl2 ethernet-1/1 - frr1 eth2 (right,
# label_ok) and srl1 ethernet-1/1 - frr2 eth1 (wrong: srl1 ethernet-1/1 goes to frr1 eth1, label_bad). One
# description in NetBox points the wrong way (srl2 ethernet-1/2 "to" frr1; it goes to frr2).
set -euo pipefail
source "$STICK_LIB/common.sh"
site=$(netbox_id "dcim/sites/?slug=stick-lab")
declare -A ifid
add_device() {  # <name> <address> <role slug> <device type slug> <platform slug> <interfaces...> (the first: mgmt)
    local name=$1 address=$2 device iface addr
    device=$(netbox_api POST dcim/devices/ "$(jq -n --arg n "$name" --argjson s "$site" \
        --argjson r "$(netbox_id "dcim/device-roles/?slug=$3")" \
        --argjson t "$(netbox_id "dcim/device-types/?slug=$4")" \
        --argjson p "$(netbox_id "dcim/platforms/?slug=$5")" \
        '{name: $n, site: $s, role: $r, device_type: $t, platform: $p, status: "active"}')" | jq -r .id)
    shift 5
    local mgmt=$1
    for ifname in "$@"; do
        iface=$(netbox_api POST dcim/interfaces/ "$(jq -n --argjson d "$device" --arg n "$ifname" \
            --argjson m "$([[ $ifname == "$mgmt" ]] && echo true || echo false)" \
            '{device: $d, name: $n, type: "1000base-t", mgmt_only: $m}')" | jq -r .id)
        ifid[$name/$ifname]=$iface
    done
    addr=$(netbox_api POST ipam/ip-addresses/ "$(jq -n --arg a "$address/24" --argjson i "${ifid[$name/$mgmt]}" \
        '{address: $a, status: "active", assigned_object_type: "dcim.interface", assigned_object_id: $i}')" \
        | jq -r .id)
    netbox_api PATCH "dcim/devices/$device/" "$(jq -n --argjson a "$addr" '{primary_ip4: $a}')" >/dev/null
}
n1=$STICK_CANARY_N1 n2=$STICK_CANARY_N2 n3=$STICK_CANARY_N3 n4=$STICK_CANARY_N4
add_device "$n1" "$STICK_NODE_SRL1_IP" spine 7220-ixr-d2l srlinux mgmt0 ethernet-1/1 ethernet-1/2 ethernet-1/3
add_device "$n2" "$STICK_NODE_SRL2_IP" spine 7220-ixr-d2l srlinux mgmt0 ethernet-1/1 ethernet-1/2 ethernet-1/3
add_device "$n3" "$STICK_NODE_FRR1_IP" leaf frr-container frr eth0 eth1 eth2 eth3
add_device "$n4" "$STICK_NODE_FRR2_IP" leaf frr-container frr eth0 eth1 eth2 eth3
netbox_api PATCH "dcim/interfaces/${ifid[$n2/ethernet-1/2]}/" "$(jq -n --arg d "to $n3" '{description: $d}')" >/dev/null
cable() {  # <a interface id> <b interface id> <label>
    netbox_api POST dcim/cables/ "$(jq -n --argjson a "$1" --argjson b "$2" --arg l "$3" \
        '{a_terminations: [{object_type: "dcim.interface", object_id: $a}],
          b_terminations: [{object_type: "dcim.interface", object_id: $b}], status: "connected", label: $l}')" >/dev/null
}
cable "${ifid[$n2/ethernet-1/1]}" "${ifid[$n3/eth2]}" "$STICK_CANARY_LABEL_OK"
cable "${ifid[$n1/ethernet-1/1]}" "${ifid[$n4/eth1]}" "$STICK_CANARY_LABEL_BAD"
