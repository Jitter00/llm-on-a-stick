#!/bin/bash
# This run's account is tried against frr2 from h1, a number of times that only this run knows. Around it:
# another unknown account tried from h2 against frr2 (a different number of times) and srl1 (twice), and a good
# login to frr2 from h1. sshd logs several lines per attempt, so the count is not a count of lines.
set -euo pipefail
source "$STICK_LIB/common.sh"
for _ in $(seq 1 "$STICK_CANARY_NOISE"); do
    ssh_login "$STICK_NODE_H2" "$STICK_NODE_FRR2_IP" "$STICK_CANARY_OTHER" not-the-password </dev/null || true
done
ssh_login "$STICK_NODE_H1" "$STICK_NODE_FRR2_IP" admin "${STICK_ADMIN_PASSWORD:-admin}" <<<"exit" >/dev/null
for _ in $(seq 1 "$STICK_CANARY_TRIES"); do
    ssh_login "$STICK_NODE_H1" "$STICK_NODE_FRR2_IP" "$STICK_CANARY_USER" not-the-password </dev/null || true
done
for _ in 1 2; do  # two only: SR Linux's sshd turns a source away after a few failures in a row
    ssh_login "$STICK_NODE_H2" "$STICK_NODE_SRL1_IP" "$STICK_CANARY_OTHER" not-the-password </dev/null || true
done
loki_wait "{host=\"frr2\"} |= \"Failed password for invalid user $STICK_CANARY_USER from\"" "$STICK_CANARY_TRIES"
loki_wait "{host=\"frr2\"} |= \"Failed password for invalid user $STICK_CANARY_OTHER from\"" "$STICK_CANARY_NOISE"
loki_wait "{host=\"srl1\"} |= \"User $STICK_CANARY_OTHER authentication failed\"" 2
