#!/bin/bash
# Four router configs on main, then two branches off it. The asked-for branch changes frr1's eth3
# description and frr2's timers and adds a note; the other one (a decoy) changes frr1 and srl1 instead.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr() {  # frr <name> <asn> <eth3 description> <eth3 address> [timers]
    cat <<CONF
hostname $1
!
interface eth3
 description $3
 ip address $4
!
router bgp $2
 neighbor 10.0.1.${1#frr} remote-as 65001
 neighbor 10.0.2.${1#frr} remote-as 65002
${5:+ timers bgp $5
}!
CONF
}
srl() { printf 'set / system name host-name %s\nset / interface ethernet-1/1 description %s\n' "$1" "$2"; }

frr frr1 65011 "$STICK_CANARY_MAIN_DESC" 10.1.1.1/24 | gitea_commit main routers/frr1.conf "Import frr1" "Ana Ruiz" 2026-09-01T09:00:00Z
frr frr2 65012 hosts-b 10.1.2.1/24 | gitea_commit main routers/frr2.conf "Import frr2" "Ana Ruiz" 2026-09-01T09:05:00Z
srl srl1 to-frr1 | gitea_commit main routers/srl1.conf "Import srl1" "Ana Ruiz" 2026-09-01T09:10:00Z
srl srl2 to-frr1 | gitea_commit main routers/srl2.conf "Import srl2" "Ana Ruiz" 2026-09-01T09:15:00Z

b="change/$STICK_CANARY_BRANCH"
gitea_branch "$b"
frr frr1 65011 "$STICK_CANARY_BRANCH_DESC" 10.1.1.1/24 | gitea_commit "$b" routers/frr1.conf "frr1: rename the host port" "Bo Lind" 2026-09-04T10:00:00Z
frr frr2 65012 hosts-b 10.1.2.1/24 "10 30" | gitea_commit "$b" routers/frr2.conf "frr2: faster BGP timers" "Bo Lind" 2026-09-04T10:05:00Z
printf 'Apply on frr1 first, then frr2.\n' | gitea_commit "$b" docs/maintenance.md "Add the maintenance note" "Bo Lind" 2026-09-04T10:10:00Z

d="change/$STICK_CANARY_DECOY"
gitea_branch "$d"
frr frr1 65011 "$STICK_CANARY_DECOY_DESC" 10.1.1.1/24 | gitea_commit "$d" routers/frr1.conf "frr1: rename the host port" "Chidi Okafor" 2026-09-06T14:00:00Z
srl srl1 to-leaf-1 | gitea_commit "$d" routers/srl1.conf "srl1: describe the uplink" "Chidi Okafor" 2026-09-06T14:05:00Z
