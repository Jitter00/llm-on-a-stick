#!/bin/bash
# Associate the waiting Elastic IP, add the default route, delete the deny entry, open 443 to the world.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
name=$STICK_CANARY_NAME host=$STICK_CANARY_HOST
q() { aws ec2 "$1" --filters "$2" --query "$3" --output text; }
inst=$(q describe-instances "Name=tag:Name,Values=$host" 'Reservations[0].Instances[0].InstanceId')
eip=$(q describe-addresses "Name=tag:Name,Values=$host" 'Addresses[0].AllocationId')
aws ec2 associate-address --allocation-id "$eip" --instance-id "$inst" >/dev/null
igw=$(q describe-internet-gateways "Name=tag:Name,Values=$name" 'InternetGateways[0].InternetGatewayId')
rtb=$(q describe-route-tables "Name=tag:Name,Values=$name-web" 'RouteTables[0].RouteTableId')
aws ec2 create-route --route-table-id "$rtb" --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw" >/dev/null
acl=$(q describe-network-acls "Name=tag:Name,Values=$name-web" 'NetworkAcls[0].NetworkAclId')
aws ec2 delete-network-acl-entry --network-acl-id "$acl" --ingress --rule-number 90
group=$(q describe-security-groups "Name=group-name,Values=$host" 'SecurityGroups[0].GroupId')
aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null
SCRIPT
