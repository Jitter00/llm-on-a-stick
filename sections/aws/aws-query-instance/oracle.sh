#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
inst=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$STICK_CANARY_HOST" \
    --query 'Reservations[0].Instances[0]' --output json)
cidr=$(aws ec2 describe-subnets --subnet-ids "$(jq -r .SubnetId <<<"$inst")" \
    --query 'Subnets[0].CidrBlock' --output text)
jq --arg c "$cidr" '{private_ip: .PrivateIpAddress, subnet_cidr: $c, security_group: .SecurityGroups[0].GroupName}' \
    <<<"$inst" > answer.json
SCRIPT
