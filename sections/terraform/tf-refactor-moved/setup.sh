#!/bin/bash
# A VPC and two subnets as separate resource blocks, applied.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
mkdir -p "$STICK_WORKSPACE/net"
cat > "$STICK_WORKSPACE/net/main.tf" <<TF
$TF_HEADER

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$name" }
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.1.0/24"
  availability_zone = "eu-west-1a"
  tags              = { Name = "$name-a" }
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.2.0/24"
  availability_zone = "eu-west-1b"
  tags              = { Name = "$name-b" }
}
TF
tf net init -input=false >/dev/null
tf net apply -auto-approve -input=false -no-color | tail -n 2
