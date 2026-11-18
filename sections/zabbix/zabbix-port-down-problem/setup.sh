#!/bin/bash
# Zabbix monitors the four routers under this run's names. One router-to-router link fails (frr2 shuts its
# eth2, so srl2's ethernet-1/2 loses its carrier too); a spare port that was never cabled is enabled on srl1
# and is down as well. Zabbix has discovered every port and polled its status once the link is down.
set -euo pipefail
source "$STICK_LIB/common.sh"
spares=(7 12 4 19 9 15 3)
spare="ethernet-1/${spares[$((STICK_CANARY_SPARE - 3))]}"
srl_commit "$STICK_NODE_SRL1" "set / interface $spare admin-state enable" "set / interface $spare description spare"

declare -A name=([srl1]=$STICK_CANARY_N_SRL1 [srl2]=$STICK_CANARY_N_SRL2 [frr1]=$STICK_CANARY_N_FRR1 [frr2]=$STICK_CANARY_N_FRR2)
declare -A ip=([srl1]=$STICK_NODE_SRL1_IP [srl2]=$STICK_NODE_SRL2_IP [frr1]=$STICK_NODE_FRR1_IP [frr2]=$STICK_NODE_FRR2_IP)
for r in frr2 srl1 frr1 srl2; do zabbix_add_host "${name[$r]}" "${ip[$r]}" stick-ro >/dev/null; done
for r in frr2 srl1 frr1 srl2; do zabbix_wait_available "${name[$r]}" 1; done
zabbix_wait_items "${name[srl1]}" "Interface $spare("
zabbix_wait_items "${name[srl2]}" "Interface ethernet-1/2("
zabbix_wait_items "${name[frr2]}" "Interface eth2("
zabbix_wait_items "${name[frr1]}" "Interface eth2("
# Port discovery stops here. Run again after the link fails (a late "execute now", or its hourly schedule),
# it would drop frr2's eth2, which is now disabled on the router, and disable that port's items.
for r in srl1 srl2 frr1 frr2; do
    hostid=$(zabbix_api host.get "$(jq -n --arg h "${name[$r]}" '{output: ["hostid"], filter: {host: [$h]}}')" | jq -er '.[0].hostid')
    rule=$(zabbix_api discoveryrule.get "$(jq -n --arg h "$hostid" '{hostids: [$h], output: ["itemid"], filter: {key_: "net.if.discovery"}}')" \
        | jq -er '.[0].itemid')
    zabbix_api discoveryrule.update "$(jq -n --arg i "$rule" '{itemid: $i, status: 1}')" >/dev/null
done
zabbix_reload

frr_conf "$STICK_NODE_FRR2" "interface eth2" "shutdown"

# status <host> <item name text>: the item's last value ("" until it is polled).
status() {
    zabbix_api item.get "$(jq -n --arg h "$1" --arg t "$2" '{host: $h, output: ["lastvalue"], search: {name: $t}}')" \
        | jq -r '.[0].lastvalue // ""'
}
want=("${name[srl2]}|Interface ethernet-1/2(to frr2): Operational status|2"
      "${name[frr2]}|Interface eth2(): Operational status|2"
      "${name[srl1]}|Interface $spare(spare): Operational status|2"
      "${name[srl1]}|Interface ethernet-1/2(to frr2): Operational status|1"
      "${name[frr1]}|Interface eth2(): Operational status|1")
for n in $(seq 1 30); do
    if (( n % 5 == 1 )); then for r in srl1 srl2 frr1 frr2; do zabbix_poll "${name[$r]}" ifOperStatus; done; fi
    ok=1
    for w in "${want[@]}"; do
        IFS='|' read -r h t v <<<"$w"
        [[ "$(status "$h" "$t")" == "$v" ]] || { ok=0; break; }
    done
    (( ok )) && exit 0
    sleep 2
done
echo "Zabbix doesn't show the ports' status as expected: $h / $t" >&2
exit 1
