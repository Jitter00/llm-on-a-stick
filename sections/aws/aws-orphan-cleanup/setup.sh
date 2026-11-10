#!/bin/bash
# The project: a running server and a stopped one, each with an attached data volume; the running one has
# an associated Elastic IP and the group "<project>-app". In use too: the group "<project>-clients" (on
# no interface, but a rule of "<project>-app" refers to it).
# The orphans: two unattached volumes, one unassociated Elastic IP, and one group (it refers to
# "<project>-app", but nothing refers to it). Another project has one orphan of each kind too, and one
# orphan-looking volume has no project tag at all.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
project=$STICK_CANARY_PROJECT other=other-$STICK_CANARY_PROJECT
tags() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$2},{Key=project,Value=$3}]"; }
volume() { aws ec2 create-volume --size 8 --availability-zone eu-west-1a --query VolumeId --output text \
    --tag-specifications "$(tags volume "$1" "$2")"; }
address() { aws ec2 allocate-address --domain vpc --query AllocationId --output text \
    --tag-specifications "$(tags elastic-ip "$1" "$2")"; }
group() { aws ec2 create-security-group --group-name "$1" --description "$1" --vpc-id "$vpc" \
    --query GroupId --output text \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=project,Value=$2}]"; }
from() { aws ec2 authorize-security-group-ingress --group-id "$1" --ip-permissions \
    "IpProtocol=tcp,FromPort=$2,ToPort=$2,UserIdGroupPairs=[{GroupId=$3}]" >/dev/null; }
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
read -r subnet vpc < <(aws ec2 describe-subnets --filters Name=availability-zone,Values=eu-west-1a \
    --query 'Subnets[0].[SubnetId,VpcId]' --output text)

app=$(group "$project-app" "$project") clients=$(group "$project-clients" "$project")
orphan=$(group "$STICK_CANARY_SG" "$project") foreign=$(group "$other-old" "$other")
from "$app" 8443 "$clients"
from "$orphan" 5432 "$app"
from "$foreign" 5432 "$app"

server() { aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$subnet" \
    --security-group-ids "$app" --tag-specifications "$(tags instance "$1" "$project")" \
    --query 'Instances[0].InstanceId' --output text; }
inst=$(server "$project-server") spare=$(server "$project-spare")
data=$(volume "$project-data" "$project")
aws ec2 attach-volume --volume-id "$data" --instance-id "$inst" --device /dev/sdf >/dev/null
aws ec2 attach-volume --volume-id "$(volume "$project-spare-data" "$project")" --instance-id "$spare" \
    --device /dev/sdf >/dev/null
aws ec2 stop-instances --instance-ids "$spare" >/dev/null
aws ec2 associate-address --allocation-id "$(address "$project-web" "$project")" --instance-id "$inst" >/dev/null

volume "$STICK_CANARY_VOL1" "$project" >/dev/null
volume "$STICK_CANARY_VOL2" "$project" >/dev/null
address "$STICK_CANARY_EIP" "$project" >/dev/null

volume other-scratch "$other" >/dev/null
address other-spare "$other" >/dev/null
aws ec2 create-volume --size 8 --availability-zone eu-west-1a \
    --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=untagged-scratch}]" >/dev/null
SCRIPT
