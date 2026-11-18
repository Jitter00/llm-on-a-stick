#!/bin/bash
# Apply a flat configuration: a VPC with an internet gateway, three subnets, their route tables and
# associations made with count over a list (web, db, app: the CIDR blocks follow the list's order, not the
# names'), a default route on the web table, a security group and an instance in the app subnet.
# The task moves the network into a module and from count to for_each, without touching the account.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
mkdir -p "$STICK_WORKSPACE/net"
cat > "$STICK_WORKSPACE/net/main.tf" <<TF
$TF_HEADER

variable "subnets" {
  description = "The subnets, in the order their CIDR blocks were handed out"
  type        = list(string)
  default     = ["web", "db", "app"]
}

data "aws_ami" "linux" {
  most_recent = true
  owners      = ["amazon"]
}

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$name" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "$name" }
}

resource "aws_subnet" "this" {
  count             = length(var.subnets)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 1)
  availability_zone = "eu-west-1a"
  tags              = { Name = "$name-\${var.subnets[count.index]}" }
}

resource "aws_route_table" "this" {
  count  = length(var.subnets)
  vpc_id = aws_vpc.main.id
  tags   = { Name = "$name-\${var.subnets[count.index]}" }
}

resource "aws_route_table_association" "this" {
  count          = length(var.subnets)
  subnet_id      = aws_subnet.this[count.index].id
  route_table_id = aws_route_table.this[count.index].id
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.this[0].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_security_group" "web" {
  name        = "$name-app"
  description = "app"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = 8080
    to_port     = 8080
    cidr_blocks = [aws_subnet.this[0].cidr_block]
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.linux.id
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.this[2].id
  vpc_security_group_ids = [aws_security_group.web.id]
  tags                   = { Name = "$name-app" }

  lifecycle {
    ignore_changes = [ami]
  }
}
TF
tf net init -input=false >/dev/null
tf net apply -auto-approve -input=false -no-color | tail -n 2
