#!/bin/bash
# Every router gets a service address of this run on a loopback. The zone has frr1 right, frr2 with an older
# address, srl1 right but disabled (DNS doesn't answer it) and no record for srl2.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR1" "interface lo" "ip address $STICK_CANARY_A_FRR1/32"
frr_conf "$STICK_NODE_FRR2" "interface lo" "ip address $STICK_CANARY_A_FRR2/32"
srl_set "$STICK_NODE_SRL1" "set / interface lo0 admin-state enable subinterface 0 ipv4 admin-state enable address $STICK_CANARY_A_SRL1/32"
srl_set "$STICK_NODE_SRL2" "set / interface lo0 admin-state enable subinterface 0 ipv4 admin-state enable address $STICK_CANARY_A_SRL2/32"

pdns_zone stick.lab.
pdns_rrset stick.lab. ns1.stick.lab. A 3600 198.18.255.53
pdns_rrset stick.lab. frr1.stick.lab. A 300 "$STICK_CANARY_A_FRR1"
pdns_rrset stick.lab. frr2.stick.lab. A 300 "$STICK_CANARY_STALE"
pdns_rrset stick.lab. srl1.stick.lab. A 300 "!$STICK_CANARY_A_SRL1"
pdns_rrset stick.lab. srl1.stick.lab. TXT 300 '"spine 1"'
pdns_rrset stick.lab. srl2.stick.lab. TXT 300 '"spine 2"'
pdns_rrset stick.lab. h1.stick.lab. A 300 198.18.255.101
