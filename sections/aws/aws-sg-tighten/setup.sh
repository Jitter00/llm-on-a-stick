#!/bin/bash
# The instance has two security groups: "<sg>" opens SSH to the world (plus HTTPS, and PostgreSQL from 10/8),
# "<sg>-mgmt" allows SSH from 10/8 only and is a distractor. A second instance shares the open group.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
sg=$STICK_CANARY_SG
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
vpc=$(aws ec2 create-vpc --cidr-block 10.50.0.0/16 --query Vpc.VpcId --output text)
subnet=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.50.1.0/24 --availability-zone eu-west-1a \
    --query Subnet.SubnetId --output text)
group() { aws ec2 create-security-group --group-name "$1" --description "$1" --vpc-id "$vpc" \
    --query GroupId --output text; }
allow() { aws ec2 authorize-security-group-ingress --group-id "$1" --protocol tcp --port "$2" --cidr "$3" >/dev/null; }
open=$(group "$sg")
allow "$open" 443 0.0.0.0/0
allow "$open" 22 0.0.0.0/0
allow "$open" 5432 10.0.0.0/8
mgmt=$(group "$sg-mgmt")
allow "$mgmt" 22 10.0.0.0/8
for name in "$STICK_CANARY_HOST" "$STICK_CANARY_HOST-2"; do
    aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$subnet" \
        --security-group-ids "$mgmt" "$open" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$name}]" >/dev/null
done
SCRIPT
