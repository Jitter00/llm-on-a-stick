#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
alloc=$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$STICK_CANARY_EIP" \
    --query 'Addresses[0].AllocationId' --output text)
new=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$STICK_CANARY_NEW" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)
aws ec2 associate-address --allocation-id "$alloc" --instance-id "$new" --allow-reassociation >/dev/null
SCRIPT
