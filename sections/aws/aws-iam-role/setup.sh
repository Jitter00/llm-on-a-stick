#!/bin/bash
# The bucket with objects under two prefixes, a second bucket, and an existing role with a broad policy (a
# bad example to copy from, and something that must not change).
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
bucket=$STICK_CANARY_BUCKET other=$STICK_CANARY_OTHER
for b in "$bucket" "$other-archive"; do
    aws s3api create-bucket --bucket "$b" --create-bucket-configuration LocationConstraint=eu-west-1 >/dev/null
done
for key in reports/2026-10.csv reports/2026-11.csv private/salaries.csv; do
    echo data | aws s3 cp - "s3://$bucket/$key" >/dev/null
done
trust='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":["ec2.amazonaws.com","lambda.amazonaws.com"]},"Action":"sts:AssumeRole"}]}'
broad='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:*","Resource":"*"}]}'
aws iam create-role --role-name "$other" --assume-role-policy-document "$trust" >/dev/null
aws iam put-role-policy --role-name "$other" --policy-name s3-all --policy-document "$broad"
SCRIPT
