#!/bin/bash
# An older VPC that must stay as it is: the new network is built next to it.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
vpc=$(aws ec2 create-vpc --cidr-block 10.200.0.0/16 --query Vpc.VpcId --output text \
    --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=$STICK_CANARY_OLD}]")
aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.200.1.0/24 --availability-zone eu-west-1a >/dev/null
SCRIPT
