#!/bin/bash
# The role, with an instance profile, two broad inline policies and an attached managed policy that another
# role uses too. What the application uses: a bucket (objects under reports/ and private/), a queue (next
# to its dead-letter queue), a KMS key behind an alias (next to a second one) and an SSM parameter (next to
# a second one).
set -euo pipefail
source "$STICK_LIB/common.sh"
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
role=$STICK_CANARY_ROLE bucket=$STICK_CANARY_BUCKET queue=$STICK_CANARY_QUEUE other=$STICK_CANARY_OTHER
for b in "$bucket" "$bucket-archive"; do
    aws s3api create-bucket --bucket "$b" --create-bucket-configuration LocationConstraint=eu-west-1 >/dev/null
done
for object in reports/2026-10.csv reports/2026-11.csv private/salaries.csv; do
    echo data | aws s3 cp - "s3://$bucket/$object" >/dev/null
done
aws sqs create-queue --queue-name "$queue" >/dev/null
aws sqs create-queue --queue-name "$queue-dlq" >/dev/null
for alias in "$STICK_CANARY_ALIAS" "$STICK_CANARY_ALIAS-backup"; do
    cmk=$(aws kms create-key --description "$alias" --query KeyMetadata.KeyId --output text)
    aws kms create-alias --alias-name "alias/$alias" --target-key-id "$cmk"
done
aws ssm put-parameter --name "/$role/config" --value 'mode=production' --type String >/dev/null
aws ssm put-parameter --name "/$role/deploy-token" --value s3cr3t --type SecureString >/dev/null

trust='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
doc() { echo "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":$1,\"Resource\":\"*\"}]}"; }
admin=$(aws iam create-policy --policy-name "$other-poweruser" --policy-document "$(doc '"*"')" \
    --query Policy.Arn --output text)
for r in "$role" "$other"; do
    aws iam create-role --role-name "$r" --assume-role-policy-document "$trust" >/dev/null
    aws iam attach-role-policy --role-name "$r" --policy-arn "$admin"
done
aws iam put-role-policy --role-name "$role" --policy-name storage --policy-document "$(doc '["s3:*","kms:*"]')"
aws iam put-role-policy --role-name "$role" --policy-name messaging \
    --policy-document "$(doc '["sqs:*","ssm:Get*","ssm:Describe*"]')"
aws iam create-instance-profile --instance-profile-name "$role" >/dev/null
aws iam add-role-to-instance-profile --instance-profile-name "$role" --role-name "$role"
SCRIPT
