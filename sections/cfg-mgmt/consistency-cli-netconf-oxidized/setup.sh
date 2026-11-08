#!/bin/bash
# Make Oxidized's backup of srl1 current, then change srl1 so that backup is out of date in exactly one place.
set -euo pipefail
source "$STICK_LIB/common.sh"
oxidized_backup_now srl1
srl_set "$STICK_NODE_SRL1" "set / interface ethernet-1/2 description ${STICK_CANARY_NEW_DESC}"
echo "srl1 ethernet-1/2 description changed after the Oxidized backup"
