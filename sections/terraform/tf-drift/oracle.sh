#!/bin/bash
# Adopt the new instance type and import the batch subnet as it is; apply then only removes the extra rule.
# The debug group is not Terraform's: delete it by hand.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
sed -i 's/"t3.micro"/"t3.large"/' "$STICK_WORKSPACE/app/main.tf"
subnet=$(aws_cli ec2 describe-subnets --filters "Name=tag:Name,Values=$name-batch" \
    --query 'Subnets[0].SubnetId' --output text)
cat >> "$STICK_WORKSPACE/app/main.tf" <<TF

import {
  to = aws_subnet.batch
  id = "$subnet"
}

resource "aws_subnet" "batch" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.2.0/24"
  availability_zone = "eu-west-1b"
  tags              = { Name = "$name-batch", owner = "batch-team" }
}
TF
tf app apply -auto-approve -input=false -no-color | tail -n 2
debug=$(aws_cli ec2 describe-security-groups --filters "Name=group-name,Values=$name-debug" \
    --query 'SecurityGroups[0].GroupId' --output text)
aws_cli ec2 delete-security-group --group-id "$debug"
