#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
group=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$STICK_CANARY_SG" \
    --query 'SecurityGroups[0].GroupId' --output text)
aws ec2 revoke-security-group-ingress --group-id "$group" --protocol tcp --port 22 --cidr 0.0.0.0/0 >/dev/null
aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp --port 22 \
    --cidr "$STICK_CANARY_OFFICE.0/24" >/dev/null
SCRIPT
