#!/bin/bash
# Fix the CIDR block and the association, and give every rule its own resource (none inline), which breaks
# the cycle and keeps the plan clean.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
cat > "$STICK_WORKSPACE/net/main.tf" <<TF
$TF_HEADER

locals {
  subnets = {
    a = "$net.1.0/24"
    b = "$net.2.0/24"
  }
}

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$name" }
}

resource "aws_subnet" "app" {
  for_each          = local.subnets
  vpc_id            = aws_vpc.main.id
  cidr_block        = each.value
  availability_zone = "eu-west-1\${each.key}"
  tags              = { Name = "$name-\${each.key}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "$name" }

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "app" {
  for_each       = local.subnets
  subnet_id      = aws_subnet.app[each.key].id
  route_table_id = aws_route_table.main.id
}

resource "aws_security_group" "web" {
  name        = "$name-web"
  description = "web servers"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "db" {
  name        = "$name-db"
  description = "database"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "web_https" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "web_to_db" {
  security_group_id            = aws_security_group.web.id
  referenced_security_group_id = aws_security_group.db.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "db_from_web" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
TF
tf net apply -auto-approve -input=false -no-color | tail -n 2
