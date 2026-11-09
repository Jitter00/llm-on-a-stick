#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
role=$STICK_CANARY_ROLE bucket=$STICK_CANARY_BUCKET
trust='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
policy=$(jq -n --arg b "arn:aws:s3:::$bucket" '{Version: "2012-10-17", Statement: [
    {Effect: "Allow", Action: "s3:GetObject", Resource: ($b + "/reports/*")},
    {Effect: "Allow", Action: "s3:ListBucket", Resource: $b}]}')
aws iam create-role --role-name "$role" --assume-role-policy-document "$trust" >/dev/null
aws iam put-role-policy --role-name "$role" --policy-name s3-read --policy-document "$policy"
aws iam create-instance-profile --instance-profile-name "$role" >/dev/null
aws iam add-role-to-instance-profile --instance-profile-name "$role" --role-name "$role"
SCRIPT
