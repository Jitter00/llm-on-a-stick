#!/bin/bash
# This run's account logs in to srl2 from h1 and commits a new BGP router-id (this run's): both of srl2's
# sessions drop. Around it, so that no single search finds the answer:
#   - the other account commits a harmless change (an interface description) on srl1, from h2, just before
#   - this run's account also logs in to srl1, from h2, and only looks
#   - frr1 resets its session to srl1: a session that drops with no configuration change behind it
set -euo pipefail
source "$STICK_LIB/common.sh"
password="Stick-$STICK_CANARY_DESC"
for node in "$STICK_NODE_SRL1" "$STICK_NODE_SRL2"; do
    srl_commit "$node" \
        "set / system aaa authorization role netops services [ cli ]" \
        "set / system configuration role netops rule / action write" \
        "set / system aaa authentication user $STICK_CANARY_USER password $password role [ netops ]" \
        "set / system aaa authentication user $STICK_CANARY_OTHER password $password role [ netops ]"
done
login() {  # <from> <router address> <user>, commands on stdin. A new account takes a moment to exist.
    local commands; commands=$(cat)
    for _ in $(seq 1 15); do
        ssh_login "$1" "$2" "$3" "$password" <<<"$commands" >/dev/null && return 0
        sleep 2
    done
    echo "login of $3 to $2 failed" >&2
    return 1
}
login "$STICK_NODE_H2" "$STICK_NODE_SRL1_IP" "$STICK_CANARY_OTHER" <<SRL
enter candidate
set / interface ethernet-1/2 description $STICK_CANARY_DESC
commit now
quit
SRL
sleep 3
login "$STICK_NODE_H2" "$STICK_NODE_SRL1_IP" "$STICK_CANARY_USER" <<SRL
show network-instance default protocols bgp neighbor
quit
SRL
frr_cli "$STICK_NODE_FRR1" "clear bgp 10.0.1.0" >/dev/null
sleep 5
login "$STICK_NODE_H1" "$STICK_NODE_SRL2_IP" "$STICK_CANARY_USER" <<SRL
enter candidate
set / network-instance default protocols bgp router-id $STICK_CANARY_RID
commit now
quit
SRL
loki_wait "{host=\"srl2\"} |= \"commitSucceeded\" |= \"by user $STICK_CANARY_USER \"" 1
loki_wait "{host=\"srl1\"} |= \"commitSucceeded\" |= \"by user $STICK_CANARY_OTHER \"" 1
loki_wait '{host="srl2"} |= "bgpNeighborBackwardTransition" |= "ESTABLISHED to lower state IDLE due to event CONFIG_CHG"' 2
loki_wait '{host="frr1"} |= "ADJCHANGE: neighbor 10.0.1.0" |= "Down User reset"' 1
[[ "$(loki_count "{host=\"srl1\"} |= \"commitSucceeded\" |= \"by user $STICK_CANARY_USER \"")" -eq 0 ]]
