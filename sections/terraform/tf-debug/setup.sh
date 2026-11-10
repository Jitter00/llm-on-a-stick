#!/bin/bash
# An older VPC that must stay as it is, and the broken configuration (initialised, never applied):
#   - the route table associations use aws_subnet.app.id, but aws_subnet.app has for_each (validate fails);
#   - the two security groups refer to each other in their inline rules: a dependency cycle;
#   - subnet b's CIDR block has a typo and lies outside the VPC (the apply fails half-way).
# Moving only the two cross-referencing rules out of the groups leaves "web" with an inline ingress block
# next to a separate rule resource: that applies, but the plan is never clean.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
other=${net%.*}.$(((${net##*.} + 1) % 256))
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
vpc=$(aws ec2 create-vpc --cidr-block 10.200.0.0/16 --query Vpc.VpcId --output text \
    --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=$STICK_CANARY_OLD}]")
aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.200.1.0/24 --availability-zone eu-west-1a >/dev/null
SCRIPT
mkdir -p "$STICK_WORKSPACE/net"
cat > "$STICK_WORKSPACE/net/main.tf" <<TF
$TF_HEADER

locals {
  subnets = {
    a = "$net.1.0/24"
    b = "$other.2.0/24"
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
  subnet_id      = aws_subnet.app.id
  route_table_id = aws_route_table.main.id
}

resource "aws_security_group" "web" {
  name        = "$name-web"
  description = "web servers"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.db.id]
  }
}

resource "aws_security_group" "db" {
  name        = "$name-db"
  description = "database"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.web.id]
  }
}
TF
tf net init -input=false >/dev/null
