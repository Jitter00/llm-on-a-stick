#!/bin/bash
# Two instances in two subnets of one VPC, each with its own security group: the answer is the first one's.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
net=$STICK_CANARY_VPC
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
vpc=$(aws ec2 create-vpc --cidr-block "$net.0.0/16" --query Vpc.VpcId --output text)
launch() {  # launch <name> <third octet> <security group name>
    local subnet group
    subnet=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block "$net.$2.0/24" \
        --availability-zone eu-west-1a --query Subnet.SubnetId --output text)
    group=$(aws ec2 create-security-group --group-name "$3" --description "$3" --vpc-id "$vpc" \
        --query GroupId --output text)
    aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$subnet" \
        --private-ip-address "$net.$2.10" --security-group-ids "$group" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$1}]" >/dev/null
}
launch "$STICK_CANARY_HOST" 1 "$STICK_CANARY_SG"
launch "$STICK_CANARY_OTHER" 2 "$STICK_CANARY_OTHER-sg"
SCRIPT
