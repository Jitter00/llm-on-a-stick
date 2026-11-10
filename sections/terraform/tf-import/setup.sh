#!/bin/bash
# A hand-made network with settings that differ from Terraform's defaults (DNS hostnames on, public addresses
# at launch, a description on the group), so a configuration written without reading them plans changes.
# With an internet gateway and a route table with a default route to it: five resources to import.
set -euo pipefail
source "$STICK_LIB/common.sh"
mkdir -p "$STICK_WORKSPACE/legacy"
printf '%s\n' "$TF_HEADER" > "$STICK_WORKSPACE/legacy/main.tf"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
tag() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$2},{Key=owner,Value=netops}]"; }
vpc=$(aws ec2 create-vpc --cidr-block "$net.0.0/16" --tag-specifications "$(tag vpc "$name")" \
    --query Vpc.VpcId --output text)
aws ec2 modify-vpc-attribute --vpc-id "$vpc" --enable-dns-hostnames
subnet=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block "$net.1.0/24" --availability-zone eu-west-1b \
    --tag-specifications "$(tag subnet "$name-a")" --query Subnet.SubnetId --output text)
aws ec2 modify-subnet-attribute --subnet-id "$subnet" --map-public-ip-on-launch
group=$(aws ec2 create-security-group --group-name "$name-web" --description "web tier, made by hand" \
    --vpc-id "$vpc" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null
aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp --port 8080 --cidr "$net.0.0/16" >/dev/null
igw=$(aws ec2 create-internet-gateway --tag-specifications "$(tag internet-gateway "$name")" \
    --query InternetGateway.InternetGatewayId --output text)
aws ec2 attach-internet-gateway --vpc-id "$vpc" --internet-gateway-id "$igw"
rtb=$(aws ec2 create-route-table --vpc-id "$vpc" --tag-specifications "$(tag route-table "$name-public")" \
    --query RouteTable.RouteTableId --output text)
aws ec2 create-route --route-table-id "$rtb" --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw" >/dev/null
SCRIPT
