#!/bin/bash
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

resource "aws_subnet" "app" {
  for_each          = { a = 1, b = 2 }
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.\${each.value}.0/24"
  availability_zone = "eu-west-1\${each.key}"
  tags              = { Name = "$name-\${each.key}" }
}

resource "aws_security_group" "web" {
  name        = "$name-web"
  description = "web"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = aws_vpc.main.cidr_block
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}
TF
tf net init -input=false >/dev/null
tf net apply -auto-approve -input=false -no-color | tail -n 2
