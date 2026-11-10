#!/bin/bash
# Eight instances, each with the group "base" (HTTPS from anywhere) and a group of its own, plus one open
# group that no instance uses. Exposed: TCP 22 from 0.0.0.0/0 (on a stopped instance), TCP 0-1024 from
# 0.0.0.0/0, every protocol from 0.0.0.0/0, TCP 22 from ::/0. Not exposed: 22 from 10.0.0.0/8, UDP 22 and
# TCP 2222 and 23-80 from anywhere, 22 from another security group, 22 to anywhere (an outbound rule).
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
ami=$(aws ec2 describe-images --owners amazon --query 'Images[0].ImageId' --output text)
vpc=$(aws ec2 create-vpc --cidr-block 10.60.0.0/16 --query Vpc.VpcId --output text)
subnet=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.60.1.0/24 --availability-zone eu-west-1a \
    --query Subnet.SubnetId --output text)
group() { aws ec2 create-security-group --group-name "$1" --description "$1" --vpc-id "$vpc" \
    --query GroupId --output text; }
ingress() { aws ec2 authorize-security-group-ingress --group-id "$1" --ip-permissions "$2" >/dev/null; }
base=$(group base)
ingress "$base" 'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]'
bastion=$(group bastion)
ingress "$bastion" 'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=10.0.0.0/8}]'
unused=$(group legacy-ssh)
ingress "$unused" 'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=0.0.0.0/0}]'
launch() {  # launch <name> <rule>...: an instance with "base" and its own group holding the rules
    local name=$1 own inst rule
    shift
    own=$(group "$name")
    for rule in "$@"; do
        if [[ $rule == egress:* ]]; then
            aws ec2 authorize-security-group-egress --group-id "$own" --ip-permissions "${rule#egress:}" >/dev/null
        else
            ingress "$own" "$rule"
        fi
    done
    aws ec2 run-instances --image-id "$ami" --instance-type t3.micro --subnet-id "$subnet" \
        --security-group-ids "$base" "$own" --query 'Instances[0].InstanceId' --output text \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$name}]"
}
all='IpRanges=[{CidrIp=0.0.0.0/0}]'
launch "$STICK_CANARY_INTERNAL" 'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=10.0.0.0/8}]' >/dev/null
launch "$STICK_CANARY_RANGE" "IpProtocol=tcp,FromPort=0,ToPort=1024,$all" >/dev/null
launch "$STICK_CANARY_OTHERPORT" "IpProtocol=udp,FromPort=22,ToPort=22,$all" \
    "IpProtocol=tcp,FromPort=2222,ToPort=2222,$all" "IpProtocol=tcp,FromPort=23,ToPort=80,$all" >/dev/null
stopped=$(launch "$STICK_CANARY_PLAIN" "IpProtocol=tcp,FromPort=22,ToPort=22,$all")
launch "$STICK_CANARY_VIAGROUP" "IpProtocol=tcp,FromPort=22,ToPort=22,UserIdGroupPairs=[{GroupId=$bastion}]" >/dev/null
launch "$STICK_CANARY_IPV6" 'IpProtocol=tcp,FromPort=22,ToPort=22,Ipv6Ranges=[{CidrIpv6=::/0}]' \
    'IpProtocol=tcp,FromPort=8080,ToPort=8080,IpRanges=[{CidrIp=10.0.0.0/8}]' >/dev/null
launch "$STICK_CANARY_EGRESS" "egress:IpProtocol=tcp,FromPort=22,ToPort=22,$all" \
    'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=192.168.0.0/16}]' >/dev/null
launch "$STICK_CANARY_ALLPROTO" "IpProtocol=-1,$all" >/dev/null
aws ec2 stop-instances --instance-ids "$stopped" >/dev/null
SCRIPT
