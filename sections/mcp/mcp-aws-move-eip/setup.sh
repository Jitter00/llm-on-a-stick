#!/bin/bash
# Three instances in one subnet: the old one (stopped) holds this run's Elastic IP, the new one has none,
# and a standby one holds a second Elastic IP whose Name tag starts the same way.
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
net=$STICK_CANARY_NET
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
vpc=$(aws ec2 create-vpc --cidr-block "$net.0.0/16" --query Vpc.VpcId --output text)
subnet=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block "$net.1.0/24" --availability-zone eu-west-1a \
    --query Subnet.SubnetId --output text)
launch() {  # launch <name> <last octet>  -> instance id
    aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$subnet" \
        --private-ip-address "$net.1.$2" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$1}]" \
        --query 'Instances[0].InstanceId' --output text
}
address() {  # address <name> <instance id>
    local alloc
    alloc=$(aws ec2 allocate-address --domain vpc \
        --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$1}]" \
        --query AllocationId --output text)
    aws ec2 associate-address --allocation-id "$alloc" --instance-id "$2" >/dev/null
}
standby=$(launch "$STICK_CANARY_NEW-standby" 12)
old=$(launch "$STICK_CANARY_OLD" 10)
launch "$STICK_CANARY_NEW" 11 >/dev/null
address "$STICK_CANARY_EIP-spare" "$standby"
address "$STICK_CANARY_EIP" "$old"
aws ec2 stop-instances --instance-ids "$old" >/dev/null
SCRIPT
