#!/bin/bash
# One VPC, three subnets. "<name>-dmz" works: the other web server, with an Elastic IP, a route table with
# a default route to the internet gateway, the VPC's default network ACL and a group that allows 443.
# "<name>-web" holds the broken server, with four faults:
#   - no public address (an Elastic IP with its Name tag is allocated, but not associated);
#   - its subnet's route table has no default route;
#   - its subnet's network ACL denies TCP 443 inbound (rule 90) before the allow-all rule 100;
#   - its security group allows 443 from 10.0.0.0/8 only.
# "<name>-db" (a database server) stays on the main route table, which has no default route.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME host=$STICK_CANARY_HOST other=$STICK_CANARY_OTHER
tag() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$2}]"; }
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
vpc=$(aws ec2 create-vpc --cidr-block "$net.0.0/16" --tag-specifications "$(tag vpc "$name")" \
    --query Vpc.VpcId --output text)
subnet() { aws ec2 create-subnet --vpc-id "$vpc" --cidr-block "$net.$2.0/24" --availability-zone eu-west-1a \
    --tag-specifications "$(tag subnet "$name-$1")" --query Subnet.SubnetId --output text; }
web=$(subnet web 1) dmz=$(subnet dmz 2) db=$(subnet db 3)
igw=$(aws ec2 create-internet-gateway --tag-specifications "$(tag internet-gateway "$name")" \
    --query InternetGateway.InternetGatewayId --output text)
aws ec2 attach-internet-gateway --vpc-id "$vpc" --internet-gateway-id "$igw"
table() { aws ec2 create-route-table --vpc-id "$vpc" --tag-specifications "$(tag route-table "$1")" \
    --query RouteTable.RouteTableId --output text; }
rt_dmz=$(table "$name-dmz") rt_web=$(table "$name-web")
aws ec2 create-route --route-table-id "$rt_dmz" --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw" >/dev/null
aws ec2 associate-route-table --route-table-id "$rt_dmz" --subnet-id "$dmz" >/dev/null
aws ec2 associate-route-table --route-table-id "$rt_web" --subnet-id "$web" >/dev/null

acl=$(aws ec2 create-network-acl --vpc-id "$vpc" --tag-specifications "$(tag network-acl "$name-web")" \
    --query NetworkAcl.NetworkAclId --output text)
entry() { aws ec2 create-network-acl-entry --network-acl-id "$acl" --cidr-block 0.0.0.0/0 "$@"; }
entry --ingress --rule-number 90 --protocol 6 --port-range From=443,To=443 --rule-action deny
entry --ingress --rule-number 100 --protocol -1 --rule-action allow
entry --egress --rule-number 100 --protocol -1 --rule-action allow
assoc=$(aws ec2 describe-network-acls --filters "Name=association.subnet-id,Values=$web" \
    --query "NetworkAcls[0].Associations[?SubnetId=='$web'].NetworkAclAssociationId" --output text)
aws ec2 replace-network-acl-association --association-id "$assoc" --network-acl-id "$acl" >/dev/null

group() { aws ec2 create-security-group --group-name "$1" --description "$1" --vpc-id "$vpc" \
    --query GroupId --output text; }
allow() { aws ec2 authorize-security-group-ingress --group-id "$1" --protocol tcp --port "$2" --cidr "$3" >/dev/null; }
sg_web=$(group "$host") sg_other=$(group "$other") sg_db=$(group "$name-db")
allow "$sg_web" 443 10.0.0.0/8
allow "$sg_web" 22 10.0.0.0/8
allow "$sg_other" 443 0.0.0.0/0
allow "$sg_other" 22 10.0.0.0/8
allow "$sg_db" 5432 "$net.0.0/16"
launch() { aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$2" \
    --security-group-ids "$3" --tag-specifications "$(tag instance "$1")" \
    --query 'Instances[0].InstanceId' --output text; }
launch "$host" "$web" "$sg_web" >/dev/null
i_other=$(launch "$other" "$dmz" "$sg_other")
launch "$name-db" "$db" "$sg_db" >/dev/null
address() { aws ec2 allocate-address --domain vpc --tag-specifications "$(tag elastic-ip "$1")" \
    --query AllocationId --output text; }
aws ec2 associate-address --allocation-id "$(address "$other")" --instance-id "$i_other" >/dev/null
address "$host" >/dev/null
SCRIPT
