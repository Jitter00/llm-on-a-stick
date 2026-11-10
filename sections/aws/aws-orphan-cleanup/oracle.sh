#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
filter="Name=tag:project,Values=$STICK_CANARY_PROJECT"
for vol in $(aws ec2 describe-volumes --filters "$filter" Name=status,Values=available \
        --query 'Volumes[].VolumeId' --output text); do
    aws ec2 delete-volume --volume-id "$vol"
done
for eip in $(aws ec2 describe-addresses --filters "$filter" \
        --query 'Addresses[?AssociationId==null].AllocationId' --output text); do
    aws ec2 release-address --allocation-id "$eip"
done
used=$(aws ec2 describe-network-interfaces --query 'NetworkInterfaces[].Groups[].GroupId' --output text
    aws ec2 describe-security-groups --query 'SecurityGroups[].IpPermissions[].UserIdGroupPairs[].GroupId' --output text
    aws ec2 describe-security-groups --query 'SecurityGroups[].IpPermissionsEgress[].UserIdGroupPairs[].GroupId' --output text)
for group in $(aws ec2 describe-security-groups --filters "$filter" --query 'SecurityGroups[].GroupId' --output text); do
    grep -qw "$group" <<<"$used" || aws ec2 delete-security-group --group-id "$group"
done
SCRIPT
