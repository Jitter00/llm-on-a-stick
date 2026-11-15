#!/bin/bash
# A history of routers/frr2.conf in which the commit that says it removes a neighbour removes another one,
# and the neighbour asked about goes away in a commit whose message is about timers.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr2() {  # frr2 <uplink description> <timers or ""> <neighbour lines...>
    local desc=$1 timers=$2; shift 2
    printf 'hostname frr2\n!\ninterface eth1\n description %s\n!\nrouter bgp 65012\n' "$desc"
    printf ' neighbor 10.0.1.2 remote-as 65001\n neighbor 10.0.2.2 remote-as 65002\n'
    [[ $# -gt 0 ]] && printf ' %s\n' "$@"
    [[ -n "$timers" ]] && printf ' timers bgp %s\n' "$timers"
    printf '!\n'
}
frr1() { printf 'hostname frr1\n!\nrouter bgp 65011\n neighbor 10.0.1.0 remote-as 65001\n%s!\n' "${1:+ timers bgp $1
}"; }
gone="neighbor $STICK_CANARY_GONE remote-as $STICK_CANARY_GONE_AS"
other="neighbor $STICK_CANARY_OTHER remote-as $STICK_CANARY_OTHER_AS"
f=routers/frr2.conf

frr1 "" | gitea_commit main routers/frr1.conf "Import frr1" "Ana Ruiz" 2026-09-01T09:00:00Z
frr2 uplink "" "$other" "$gone" | gitea_commit main $f "Import frr2" "Ana Ruiz" 2026-09-01T09:05:00Z
frr2 to-srl1 "" "$other" "$gone" | gitea_commit main $f "frr2: describe the uplink (ticket $STICK_CANARY_T_DESCRIBE)" "Bo Lind" 2026-09-03T11:00:00Z
frr2 to-srl1 "" "$gone" | gitea_commit main $f "frr2: remove the decommissioned neighbor (ticket $STICK_CANARY_T_DECOM)" "Chidi Okafor" 2026-09-05T15:30:00Z
frr2 to-srl1 "10 30" | gitea_commit main $f "frr2: update the BGP timers (ticket $STICK_CANARY_TICKET)" "Dana Petrov" 2026-09-08T08:45:00Z
frr1 "10 30" | gitea_commit main routers/frr1.conf "frr1: update the BGP timers (ticket $STICK_CANARY_T_FRR1)" "Ana Ruiz" 2026-09-10T08:45:00Z
frr2 to-srl1-e1-1 "10 30" | gitea_commit main $f "frr2: name the port in the uplink description (ticket $STICK_CANARY_T_TYPO)" "Bo Lind" 2026-09-12T13:20:00Z
