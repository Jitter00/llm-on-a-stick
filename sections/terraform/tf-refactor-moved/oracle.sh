#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
cat > "$STICK_WORKSPACE/net/main.tf" <<TF
$TF_HEADER

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$name" }
}

resource "aws_subnet" "app" {
  for_each          = { a = 1, b = 2, c = 3 }
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.\${each.value}.0/24"
  availability_zone = "eu-west-1\${each.key}"
  tags              = { Name = "$name-\${each.key}" }
}

moved {
  from = aws_subnet.a
  to   = aws_subnet.app["a"]
}

moved {
  from = aws_subnet.b
  to   = aws_subnet.app["b"]
}
TF
tf net apply -auto-approve -input=false -no-color | tail -n 2
