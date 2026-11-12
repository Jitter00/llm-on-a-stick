#!/bin/bash
# frr2's eth3 gets two more addresses (this run's, and a second one that only the answer names); frr1's eth3
# gets another, so "the port with an extra address" is not unique. LibreNMS monitors both and srl1, and has
# discovered them after the change, so the addresses are in its database, each tied to a port by its id only.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR2" "interface eth3" "ip address $STICK_CANARY_ADDR/32" "ip address $STICK_CANARY_SECOND/32"
frr_conf "$STICK_NODE_FRR1" "interface eth3" "ip address $STICK_CANARY_OTHER/32"
wait_address() {  # <router address> <address>: until the router's SNMP agent lists it
    local out
    for _ in $(seq 1 60); do
        out=$(docker exec stick-librenms-librenms-1 snmpbulkwalk -v2c -c stick-ro -t 2 -r 0 -OQ "$1" \
            IP-MIB::ipAdEntIfIndex 2>/dev/null || true)
        grep -qF -- "ipAdEntIfIndex.$2 " <<<"$out" && return 0
        sleep 1
    done
    echo "$1 does not list $2 over SNMP" >&2
    return 1
}
wait_address "$STICK_NODE_FRR2_IP" "$STICK_CANARY_ADDR"
wait_address "$STICK_NODE_FRR2_IP" "$STICK_CANARY_SECOND"
wait_address "$STICK_NODE_FRR1_IP" "$STICK_CANARY_OTHER"
librenms_add_devices stick-ro "$STICK_NODE_SRL1_IP" "$STICK_NODE_FRR1_IP" "$STICK_NODE_FRR2_IP"
