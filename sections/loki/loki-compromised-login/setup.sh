#!/bin/bash
# One address (h1) tries accounts against several routers: frr1 and frr2 (this run's numbers of attempts,
# rotating between this run's account, root and netops, so the lines don't all read the same), then srl2,
# where two attempts fail and the third, with this run's account, gets in and commits a new description.
# Around it:
#   - h2 fails three times too (twice on frr1, once on srl1): fewer, and it never gets in with a failure before;
#   - this run's other account logs in to srl2 from h2 and commits another description, after the attacker,
#     so "the last commit on srl2" is the wrong one.
set -euo pipefail
source "$STICK_LIB/common.sh"
password="Stick-$STICK_CANARY_PASS"
srl_commit "$STICK_NODE_SRL2" \
    "set / system aaa authorization role netops services [ cli ]" \
    "set / system configuration role netops rule / action write" \
    "set / system aaa authentication user $STICK_CANARY_USER password $password role [ netops ]" \
    "set / system aaa authentication user $STICK_CANARY_OTHER password $password role [ netops ]"
fail() { ssh_login "$1" "$2" "$3" not-the-password </dev/null || true; }
login() {  # <from> <router address> <user>, commands on stdin. A new account takes a moment to exist.
    local commands; commands=$(cat)
    for _ in $(seq 1 15); do
        ssh_login "$1" "$2" "$3" "$password" <<<"$commands" >/dev/null && return 0
        sleep 2
    done
    echo "login of $3 to $2 failed" >&2
    return 1
}
# Wait until the new accounts can log in (looking only), before any failure is logged against srl2.
login "$STICK_NODE_H2" "$STICK_NODE_SRL2_IP" "$STICK_CANARY_OTHER" <<<"quit"

fail "$STICK_NODE_H2" "$STICK_NODE_FRR1_IP" "$STICK_CANARY_OTHER"
users=("$STICK_CANARY_USER" root netops)
for i in $(seq 0 $((STICK_CANARY_TRIES1 - 1))); do fail "$STICK_NODE_H1" "$STICK_NODE_FRR1_IP" "${users[i % 3]}"; done
fail "$STICK_NODE_H2" "$STICK_NODE_SRL1_IP" "$STICK_CANARY_OTHER"
for i in $(seq 0 $((STICK_CANARY_TRIES2 - 1))); do fail "$STICK_NODE_H1" "$STICK_NODE_FRR2_IP" "${users[(i + 1) % 3]}"; done
fail "$STICK_NODE_H2" "$STICK_NODE_FRR1_IP" "$STICK_CANARY_OTHER"
fail "$STICK_NODE_H1" "$STICK_NODE_SRL2_IP" admin
fail "$STICK_NODE_H1" "$STICK_NODE_SRL2_IP" root
login "$STICK_NODE_H1" "$STICK_NODE_SRL2_IP" "$STICK_CANARY_USER" <<SRL
enter candidate
set / interface ethernet-1/1 description $STICK_CANARY_DESC
commit now
quit
SRL
sleep 3
login "$STICK_NODE_H2" "$STICK_NODE_SRL2_IP" "$STICK_CANARY_OTHER" <<SRL
enter candidate
set / interface ethernet-1/2 description $STICK_CANARY_DECOY
commit now
quit
SRL

from() { echo "{job=\"syslog\", host=\"$1\"} |= \"Failed password for \" |= \" from $2 port \""; }
loki_wait "$(from frr1 "$STICK_NODE_H1_IP")" "$STICK_CANARY_TRIES1"
loki_wait "$(from frr2 "$STICK_NODE_H1_IP")" "$STICK_CANARY_TRIES2"
loki_wait "$(from srl2 "$STICK_NODE_H1_IP")" 2
loki_wait "$(from frr1 "$STICK_NODE_H2_IP")" 2
loki_wait "$(from srl1 "$STICK_NODE_H2_IP")" 1
loki_wait "{host=\"srl2\"} |= \"commitSucceeded\" |= \"by user $STICK_CANARY_USER \"" 1
loki_wait "{host=\"srl2\"} |= \"commitSucceeded\" |= \"by user $STICK_CANARY_OTHER \"" 1
