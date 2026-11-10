#!/bin/bash
# Three hosts under random names, each with a "circuit" tag; the answer is the second (srl2). Nothing is
# polled: the answer is in what Zabbix was told, not in what it found.
set -euo pipefail
source "$STICK_LIB/common.sh"
tag() { jq -n --arg v "$1" '{tags: [{tag: "circuit", value: $v}, {tag: "role", value: "router"}]}'; }
zabbix_add_host "$STICK_CANARY_N1" "$STICK_NODE_SRL1_IP" stick-ro "$(tag "$STICK_CANARY_OTHER")" >/dev/null
zabbix_add_host "$STICK_CANARY_N2" "$STICK_NODE_SRL2_IP" stick-ro "$(tag "$STICK_CANARY_CIRCUIT")" >/dev/null
zabbix_add_host "$STICK_CANARY_N3" "$STICK_NODE_FRR1_IP" stick-ro "$(tag "${STICK_CANARY_CIRCUIT}-b")" >/dev/null
