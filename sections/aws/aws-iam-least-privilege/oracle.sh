#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
role=$STICK_CANARY_ROLE bucket=arn:aws:s3:::$STICK_CANARY_BUCKET
account=$(aws sts get-caller-identity --query Account --output text)
cmk=$(aws kms describe-key --key-id "alias/$STICK_CANARY_ALIAS" --query KeyMetadata.Arn --output text)
policy=$(jq -n --arg b "$bucket" --arg k "$cmk" \
    --arg q "arn:aws:sqs:eu-west-1:$account:$STICK_CANARY_QUEUE" \
    --arg p "arn:aws:ssm:eu-west-1:$account:parameter/$role/config" '{Version: "2012-10-17", Statement: [
    {Effect: "Allow", Action: "s3:GetObject", Resource: ($b + "/reports/*")},
    {Effect: "Allow", Action: "s3:ListBucket", Resource: $b},
    {Effect: "Allow", Action: ["sqs:ReceiveMessage", "sqs:DeleteMessage"], Resource: $q},
    {Effect: "Allow", Action: "kms:Decrypt", Resource: $k},
    {Effect: "Allow", Action: "ssm:GetParameter", Resource: $p}]}')
aws iam put-role-policy --role-name "$role" --policy-name app --policy-document "$policy"
for name in storage messaging; do aws iam delete-role-policy --role-name "$role" --policy-name "$name"; done
for arn in $(aws iam list-attached-role-policies --role-name "$role" \
        --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name "$role" --policy-arn "$arn"
done
SCRIPT
