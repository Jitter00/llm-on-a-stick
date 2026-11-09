#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
# A plan file outside the workspace lives in the container that made it: plan and show in one container.
toolbox_run net bash -euo pipefail -c 'terraform plan -input=false -out=/tmp/plan >/dev/null
    terraform show -json /tmp/plan' | jq '[.resource_changes[] | {address, a: (.change.actions | join(","))}]
    | {create: [.[] | select(.a == "create") | .address],
       update: [.[] | select(.a == "update") | .address],
       replace: [.[] | select(.a == "delete,create" or .a == "create,delete") | .address],
       delete: [.[] | select(.a == "delete") | .address]}' > "$STICK_WORKSPACE/answer.json"
