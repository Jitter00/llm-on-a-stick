#!/bin/bash
# Every router's first uplink gets a description of this run, and the repository records them: correctly for
# three routers, with an older value for srl2.
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_conf "$STICK_NODE_FRR1" "interface eth1" "description $STICK_CANARY_D_FRR1"
frr_conf "$STICK_NODE_FRR2" "interface eth1" "description $STICK_CANARY_D_FRR2"
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/1 description $STICK_CANARY_D_SRL1"
srl_set "$STICK_NODE_SRL2" "set / interface ethernet-1/1 description $STICK_CANARY_D_SRL2"

intended() {  # intended <router> <interface> <description>
    cat <<YAML
# What $1 should be running. A change starts here, as a pull request; the router follows.
router: $1
interfaces:
  $2:
    description: $3
YAML
}
intended frr1 eth1 "$STICK_CANARY_D_FRR1" | gitea_commit main intended/frr1.yaml "Record frr1's uplink" "Ana Ruiz" 2026-09-01T09:00:00Z
intended frr2 eth1 "$STICK_CANARY_D_FRR2" | gitea_commit main intended/frr2.yaml "Record frr2's uplink" "Ana Ruiz" 2026-09-01T09:05:00Z
intended srl1 ethernet-1/1 "$STICK_CANARY_D_SRL1" | gitea_commit main intended/srl1.yaml "Record srl1's uplink" "Bo Lind" 2026-09-02T10:00:00Z
intended srl2 ethernet-1/1 "$STICK_CANARY_STALE" | gitea_commit main intended/srl2.yaml "Record srl2's uplink" "Bo Lind" 2026-09-02T10:05:00Z
