#!/bin/bash
# A release branch cut from main early on, with a change of its own; then, on main, two commits for one ticket
# (one per router) among unrelated ones, and a later commit to the same lines the release branch changed.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr1() {  # frr1 <uplink description> <timers> <prefix-list line> [password]
    printf 'hostname frr1\n!\ninterface eth1\n description %s\n!\n' "$1"
    printf 'ip prefix-list LAN seq 10 %s\n!\n' "$3"
    printf 'router bgp 65101\n neighbor 10.0.1.0 remote-as 65001\n neighbor 10.0.2.0 remote-as 65002\n'
    [[ -n "${4:-}" ]] && printf ' neighbor 10.0.1.0 password %s\n' "$4"
    printf ' timers bgp %s\n!\n' "$2"
}
frr2() {  # frr2 <uplink description> <extra neighbour or ""> [password]
    printf 'hostname frr2\n!\ninterface eth1\n description %s\n!\n' "$1"
    printf 'router bgp 65102\n neighbor 10.0.1.2 remote-as 65001\n neighbor 10.0.2.2 remote-as 65002\n'
    [[ -n "$2" ]] && printf ' %s\n' "$2"
    [[ -n "${3:-}" ]] && printf ' neighbor 10.0.2.2 password %s\n' "$3"
    printf '!\n'
}
loose="permit 10.1.1.0/24 le 32"; tight="permit 10.1.1.0/24"
extra="neighbor $STICK_CANARY_EXTRA remote-as $STICK_CANARY_EXTRA_AS"
T=$STICK_CANARY_TICKET

frr1 uplink "60 180" "$loose" | gitea_commit main routers/frr1.conf "Import frr1" "Ana Ruiz" 2026-09-01T09:00:00Z
frr2 uplink "" | gitea_commit main routers/frr2.conf "Import frr2" "Ana Ruiz" 2026-09-01T09:05:00Z
gitea_branch release/2026.11 main
frr1 uplink "5 15" "$loose" | gitea_commit release/2026.11 routers/frr1.conf \
    "release: faster BGP timers on frr1 (ticket $STICK_CANARY_T_REL)" "Bo Lind" 2026-09-02T10:00:00Z
frr2 "$STICK_CANARY_D_REL" "" | gitea_commit release/2026.11 routers/frr2.conf \
    "release: describe frr2's uplink (ticket $STICK_CANARY_T_REL)" "Bo Lind" 2026-09-02T10:10:00Z

frr1 "$STICK_CANARY_D_MAIN" "60 180" "$loose" | gitea_commit main routers/frr1.conf \
    "frr1: describe the uplink (ticket $STICK_CANARY_T_DESC)" "Chidi Okafor" 2026-09-03T11:00:00Z
frr1 "$STICK_CANARY_D_MAIN" "60 180" "$tight" "$STICK_CANARY_PW1" | gitea_commit main routers/frr1.conf \
    "frr1: authenticate the srl1 session, accept only the LAN itself (ticket $T)" "Dana Petrov" 2026-09-04T14:20:00Z
frr2 uplink "$extra" | gitea_commit main routers/frr2.conf \
    "frr2: add the new peer (ticket $STICK_CANARY_T_PEER)" "Ana Ruiz" 2026-09-05T09:30:00Z
frr2 uplink "$extra" "$STICK_CANARY_PW2" | gitea_commit main routers/frr2.conf \
    "frr2: authenticate the srl2 session (ticket $T)" "Dana Petrov" 2026-09-05T16:45:00Z
frr1 "$STICK_CANARY_D_MAIN" "10 30" "$tight" "$STICK_CANARY_PW1" | gitea_commit main routers/frr1.conf \
    "frr1: update the BGP timers (ticket $STICK_CANARY_T_TIMERS)" "Chidi Okafor" 2026-09-08T08:45:00Z
printf '# lab-configs\n\nTickets named in a commit message: %s is the security review.\n' "$T" \
    | gitea_commit main README.md "README: name the security review's ticket" "Bo Lind" 2026-09-09T12:00:00Z
