#!/bin/bash
# A new peering between the app and data VPCs, accepted; a route to the database's subnet on the app
# subnet's table and one back to the app's subnet on the data table; the data ACL lets the replies out to
# the app subnet; the database's group allows 5432 from the app server's group.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
name=$STICK_CANARY_NAME app=$STICK_CANARY_APP db=$STICK_CANARY_DB a=$STICK_CANARY_APP_NET d=$STICK_CANARY_DB_NET
q() { aws ec2 "$1" --filters "$2" --query "$3" --output text; }
v_app=$(q describe-vpcs "Name=tag:Name,Values=$name-app" 'Vpcs[0].VpcId')
v_data=$(q describe-vpcs "Name=tag:Name,Values=$name-data" 'Vpcs[0].VpcId')
pcx=$(aws ec2 create-vpc-peering-connection --vpc-id "$v_app" --peer-vpc-id "$v_data" \
    --query VpcPeeringConnection.VpcPeeringConnectionId --output text)
aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id "$pcx" >/dev/null
rt_app=$(q describe-route-tables "Name=tag:Name,Values=$name-app" 'RouteTables[0].RouteTableId')
rt_data=$(q describe-route-tables "Name=tag:Name,Values=$name-data" 'RouteTables[0].RouteTableId')
aws ec2 create-route --route-table-id "$rt_app" --destination-cidr-block "$d.1.0/24" \
    --vpc-peering-connection-id "$pcx" >/dev/null
aws ec2 create-route --route-table-id "$rt_data" --destination-cidr-block "$a.1.0/24" \
    --vpc-peering-connection-id "$pcx" >/dev/null
acl=$(q describe-network-acls "Name=tag:Name,Values=$name-data" 'NetworkAcls[0].NetworkAclId')
aws ec2 create-network-acl-entry --network-acl-id "$acl" --egress --rule-number 110 --protocol 6 \
    --port-range From=1024,To=65535 --cidr-block "$a.1.0/24" --rule-action allow
g_app=$(q describe-security-groups "Name=group-name,Values=$app" 'SecurityGroups[0].GroupId')
g_db=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$db" "Name=vpc-id,Values=$v_data" \
    --query 'SecurityGroups[0].GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$g_db" \
    --ip-permissions "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=$g_app}]" >/dev/null
SCRIPT
