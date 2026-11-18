#!/bin/bash
# The network goes into modules/network with for_each over a map from name to the subnet's number (web 1,
# db 2, app 3: the CIDR blocks stay where count put them), and moved blocks carry each index to its key.
# Then init (the new module) and apply: it only moves state.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
dir="$STICK_WORKSPACE/net"
mkdir -p "$dir/modules/network"
cat > "$dir/modules/network/main.tf" <<'TF'
variable "name" { type = string }
variable "cidr_block" { type = string }
variable "subnets" {
  description = "Subnet name => its number in the VPC's CIDR block"
  type        = map(number)
}

resource "aws_vpc" "this" {
  cidr_block = var.cidr_block
  tags       = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "this" {
  for_each          = var.subnets
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(aws_vpc.this.cidr_block, 8, each.value)
  availability_zone = "eu-west-1a"
  tags              = { Name = "${var.name}-${each.key}" }
}

resource "aws_route_table" "this" {
  for_each = var.subnets
  vpc_id   = aws_vpc.this.id
  tags     = { Name = "${var.name}-${each.key}" }
}

resource "aws_route_table_association" "this" {
  for_each       = var.subnets
  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.this[each.key].id
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.this["web"].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

output "vpc_id" { value = aws_vpc.this.id }
output "subnets" { value = { for k, s in aws_subnet.this : k => { id = s.id, cidr_block = s.cidr_block } } }
TF
{
    cat <<TF
$TF_HEADER

data "aws_ami" "linux" {
  most_recent = true
  owners      = ["amazon"]
}

module "network" {
  source     = "./modules/network"
  name       = "$name"
  cidr_block = "$net.0.0/16"
  subnets    = { web = 1, db = 2, app = 3 }
}

moved {
  from = aws_vpc.main
  to   = module.network.aws_vpc.this
}

moved {
  from = aws_internet_gateway.main
  to   = module.network.aws_internet_gateway.this
}

moved {
  from = aws_route.internet
  to   = module.network.aws_route.internet
}
TF
    for pair in 0:web 1:db 2:app; do
        for kind in aws_subnet aws_route_table aws_route_table_association; do
            printf '\nmoved {\n  from = %s.this[%s]\n  to   = module.network.%s.this["%s"]\n}\n' \
                "$kind" "${pair%%:*}" "$kind" "${pair#*:}"
        done
    done
    cat <<TF

resource "aws_security_group" "web" {
  name        = "$name-app"
  description = "app"
  vpc_id      = module.network.vpc_id

  ingress {
    protocol    = "tcp"
    from_port   = 8080
    to_port     = 8080
    cidr_blocks = [module.network.subnets["web"].cidr_block]
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
  subnet_id              = module.network.subnets["app"].id
  vpc_security_group_ids = [aws_security_group.web.id]
  tags                   = { Name = "$name-app" }

  lifecycle {
    ignore_changes = [ami]
  }
}
TF
} > "$dir/main.tf"
tf net init -input=false >/dev/null
tf net apply -auto-approve -input=false -no-color | tail -n 2
