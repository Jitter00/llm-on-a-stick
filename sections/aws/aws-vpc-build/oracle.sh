#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
tag() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$2}]"; }
vpc=$(aws ec2 create-vpc --cidr-block "$net.0.0/16" --tag-specifications "$(tag vpc "$name")" \
    --query Vpc.VpcId --output text)
public=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block "$net.1.0/24" --availability-zone eu-west-1a \
    --tag-specifications "$(tag subnet "$name-public")" --query Subnet.SubnetId --output text)
aws ec2 modify-subnet-attribute --subnet-id "$public" --map-public-ip-on-launch
aws ec2 create-subnet --vpc-id "$vpc" --cidr-block "$net.2.0/24" --availability-zone eu-west-1b \
    --tag-specifications "$(tag subnet "$name-private")" >/dev/null
igw=$(aws ec2 create-internet-gateway --query InternetGateway.InternetGatewayId --output text)
aws ec2 attach-internet-gateway --vpc-id "$vpc" --internet-gateway-id "$igw"
rtb=$(aws ec2 create-route-table --vpc-id "$vpc" --tag-specifications "$(tag route-table "$name-public")" \
    --query RouteTable.RouteTableId --output text)
aws ec2 create-route --route-table-id "$rtb" --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw" >/dev/null
aws ec2 associate-route-table --route-table-id "$rtb" --subnet-id "$public" >/dev/null
SCRIPT
