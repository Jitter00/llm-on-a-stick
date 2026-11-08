#!/bin/bash
# Plant this run's canary on frr1, so a memorised or invented config can't pass.
set -euo pipefail
docker exec "$STICK_NODE_FRR1" vtysh \
    -c "conf t" -c "interface eth3" -c "description ${STICK_CANARY_HOST_DESC}"
echo "frr1 eth3 description set to ${STICK_CANARY_HOST_DESC}"
