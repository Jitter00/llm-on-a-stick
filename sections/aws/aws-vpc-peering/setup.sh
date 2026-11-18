#!/bin/bash
# Three VPCs:
#   "<name>-app"      (APP_NET.0.0/16): the application server <app> in subnet "<name>-app", and a batch
#                     server in subnet "<name>-batch"; each subnet has a route table of its own.
#   "<name>-data"     (DB_NET.0.0/16): the database server <db> in subnet "<name>-data", which has a route
#                     table and a network ACL of its own. Faults on this side:
#                       - the ACL lets traffic out only to DB_NET.0.0/16, so the replies to the app can't leave;
#                       - the database's group allows 5432 (and 22) from its own VPC only.
#   "<name>-data-old" (APP_NET.0.0/16 again: it overlaps the app VPC, so it can never be peered with it): a
#                     stopped server also named <db>.
# A peering request from the app VPC to the old one waits for acceptance, tagged "<name>-data": the wrong
# VPC. Nothing connects the app and data VPCs: no peering, no routes.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
name=$STICK_CANARY_NAME app=$STICK_CANARY_APP db=$STICK_CANARY_DB a=$STICK_CANARY_APP_NET d=$STICK_CANARY_DB_NET
tag() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$2}]"; }
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
vpc() { aws ec2 create-vpc --cidr-block "$1" --tag-specifications "$(tag vpc "$2")" --query Vpc.VpcId --output text; }
subnet() { aws ec2 create-subnet --vpc-id "$1" --cidr-block "$2" --availability-zone eu-west-1a \
    --tag-specifications "$(tag subnet "$3")" --query Subnet.SubnetId --output text; }
table() {
    local rt
    rt=$(aws ec2 create-route-table --vpc-id "$1" --tag-specifications "$(tag route-table "$3")" \
        --query RouteTable.RouteTableId --output text)
    aws ec2 associate-route-table --route-table-id "$rt" --subnet-id "$2" >/dev/null
}
group() { aws ec2 create-security-group --group-name "$1" --description "$1" --vpc-id "$2" \
    --query GroupId --output text; }
allow() { aws ec2 authorize-security-group-ingress --group-id "$1" --protocol tcp --port "$2" --cidr "$3" >/dev/null; }
launch() { aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$2" \
    --security-group-ids "$3" --tag-specifications "$(tag instance "$1")" \
    --query 'Instances[0].InstanceId' --output text; }

v_app=$(vpc "$a.0.0/16" "$name-app")
s_app=$(subnet "$v_app" "$a.1.0/24" "$name-app") s_batch=$(subnet "$v_app" "$a.2.0/24" "$name-batch")
table "$v_app" "$s_app" "$name-app"
table "$v_app" "$s_batch" "$name-batch"
g_app=$(group "$app" "$v_app") g_batch=$(group "$name-batch" "$v_app")
allow "$g_app" 22 "$a.0.0/16"
allow "$g_batch" 22 "$a.0.0/16"
launch "$app" "$s_app" "$g_app" >/dev/null
launch "$name-batch" "$s_batch" "$g_batch" >/dev/null

v_data=$(vpc "$d.0.0/16" "$name-data")
s_data=$(subnet "$v_data" "$d.1.0/24" "$name-data")
table "$v_data" "$s_data" "$name-data"
acl=$(aws ec2 create-network-acl --vpc-id "$v_data" --tag-specifications "$(tag network-acl "$name-data")" \
    --query NetworkAcl.NetworkAclId --output text)
aws ec2 create-network-acl-entry --network-acl-id "$acl" --ingress --rule-number 100 --protocol -1 \
    --cidr-block 10.0.0.0/8 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$acl" --egress --rule-number 100 --protocol -1 \
    --cidr-block "$d.0.0/16" --rule-action allow
assoc=$(aws ec2 describe-network-acls --filters "Name=association.subnet-id,Values=$s_data" \
    --query "NetworkAcls[0].Associations[?SubnetId=='$s_data'].NetworkAclAssociationId" --output text)
aws ec2 replace-network-acl-association --association-id "$assoc" --network-acl-id "$acl" >/dev/null
g_db=$(group "$db" "$v_data")
allow "$g_db" 5432 "$d.0.0/16"
allow "$g_db" 22 "$d.0.0/16"
launch "$db" "$s_data" "$g_db" >/dev/null

v_old=$(vpc "$a.0.0/16" "$name-data-old")
s_old=$(subnet "$v_old" "$a.1.0/24" "$name-data-old")
g_old=$(group "$name-data-old" "$v_old")
allow "$g_old" 5432 "$a.0.0/16"
old=$(launch "$db" "$s_old" "$g_old")
aws ec2 stop-instances --instance-ids "$old" >/dev/null
aws ec2 create-vpc-peering-connection --vpc-id "$v_app" --peer-vpc-id "$v_old" \
    --tag-specifications "$(tag vpc-peering-connection "$name-data")" >/dev/null
SCRIPT
