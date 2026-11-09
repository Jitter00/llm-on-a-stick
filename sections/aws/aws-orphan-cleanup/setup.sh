#!/bin/bash
# The project: one instance with an attached data volume and an associated Elastic IP (in use), two
# unattached volumes and one unassociated Elastic IP (the orphans). Another project has an unattached volume
# and an unassociated address too, and one orphan-looking volume has no project tag at all.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
project=$STICK_CANARY_PROJECT
tags() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$2},{Key=project,Value=$3}]"; }
volume() { aws ec2 create-volume --size 8 --availability-zone eu-west-1a --query VolumeId --output text \
    --tag-specifications "$(tags volume "$1" "$2")"; }
address() { aws ec2 allocate-address --domain vpc --query AllocationId --output text \
    --tag-specifications "$(tags elastic-ip "$1" "$2")"; }
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
subnet=$(aws ec2 describe-subnets --filters Name=availability-zone,Values=eu-west-1a \
    --query 'Subnets[0].SubnetId' --output text)
inst=$(aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$subnet" \
    --tag-specifications "$(tags instance "$project-server" "$project")" \
    --query 'Instances[0].InstanceId' --output text)
aws ec2 attach-volume --volume-id "$(volume "$project-data" "$project")" --instance-id "$inst" \
    --device /dev/sdf >/dev/null
aws ec2 associate-address --allocation-id "$(address "$project-web" "$project")" --instance-id "$inst" >/dev/null
volume "$STICK_CANARY_VOL1" "$project" >/dev/null
volume "$STICK_CANARY_VOL2" "$project" >/dev/null
address "$STICK_CANARY_EIP" "$project" >/dev/null
volume other-scratch "other-$project" >/dev/null
address other-spare "other-$project" >/dev/null
aws ec2 create-volume --size 8 --availability-zone eu-west-1a \
    --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=untagged-scratch}]" >/dev/null
SCRIPT
