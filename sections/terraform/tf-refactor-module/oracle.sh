#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME dir=$STICK_WORKSPACE/net
mkdir -p "$dir/modules/subnets"
cat > "$dir/modules/subnets/main.tf" <<'TF'
variable "vpc_id" { type = string }
variable "net" { type = string }
variable "name" { type = string }

resource "aws_subnet" "this" {
  for_each          = { a = 1, b = 2, c = 3 }
  vpc_id            = var.vpc_id
  cidr_block        = "${var.net}.${each.value}.0/24"
  availability_zone = "eu-west-1${each.key}"
  tags              = { Name = "${var.name}-${each.key}" }
}
TF
cat > "$dir/main.tf" <<TF
$TF_HEADER

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$name" }
}

module "subnets" {
  source = "./modules/subnets"
  vpc_id = aws_vpc.main.id
  net    = "$net"
  name   = "$name"
}

moved {
  from = aws_subnet.a
  to   = module.subnets.aws_subnet.this["a"]
}

moved {
  from = aws_subnet.b
  to   = module.subnets.aws_subnet.this["b"]
}
TF
tf net init -input=false >/dev/null
tf net apply -auto-approve -input=false -no-color | tail -n 2
