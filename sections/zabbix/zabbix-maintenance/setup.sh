#!/bin/bash
# Four routers, all in Routers. srl1 and frr1 are also in the site's group; srl2 and frr2 in groups whose
# names merely contain the site's name (a search by name finds all three).
set -euo pipefail
source "$STICK_LIB/common.sh"
routers=$(zabbix_group_id Routers)
site=$(zabbix_group_id "$STICK_CANARY_SITE")
spare=$(zabbix_group_id "${STICK_CANARY_SITE}-spare")
old=$(zabbix_group_id "old-${STICK_CANARY_SITE}")
groups() { jq -n --arg a "$routers" --arg b "$1" '{groups: [{groupid: $a}, {groupid: $b}]}'; }
zabbix_add_host srl2 "$STICK_NODE_SRL2_IP" stick-ro "$(groups "$spare")" >/dev/null
zabbix_add_host srl1 "$STICK_NODE_SRL1_IP" stick-ro "$(groups "$site")" >/dev/null
zabbix_add_host frr2 "$STICK_NODE_FRR2_IP" stick-ro "$(groups "$old")" >/dev/null
zabbix_add_host frr1 "$STICK_NODE_FRR1_IP" stick-ro "$(groups "$site")" >/dev/null
for host in srl1 srl2 frr1 frr2; do zabbix_wait_available "$host" 1; done
