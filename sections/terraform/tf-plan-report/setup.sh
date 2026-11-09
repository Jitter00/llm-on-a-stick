#!/bin/bash
# Apply a small network, then edit its configuration: the VPC's tag changes (update), one subnet's CIDR block
# changes (replace), a subnet is added (create), the security group is gone (delete), one subnet stays.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC dir=$STICK_WORKSPACE/net
mkdir -p "$dir"
config() {  # config <VPC Name tag> <CIDR of the subnet that moves> <extra blocks>
    cat > "$dir/main.tf" <<TF
$TF_HEADER

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$1" }
}

resource "aws_subnet" "$STICK_CANARY_KEEP" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.1.0/24"
  availability_zone = "eu-west-1a"
}

resource "aws_subnet" "$STICK_CANARY_MOVED" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$2"
  availability_zone = "eu-west-1b"
}
$3
TF
}
config staging "$net.2.0/24" "
resource \"aws_security_group\" \"$STICK_CANARY_GONE\" {
  name        = \"$STICK_CANARY_GONE\"
  description = \"web\"
  vpc_id      = aws_vpc.main.id
}"
tf net init -input=false >/dev/null
tf net apply -auto-approve -input=false -no-color | tail -n 2
config production "$net.20.0/24" "
resource \"aws_subnet\" \"$STICK_CANARY_ADDED\" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = \"$net.3.0/24\"
  availability_zone = \"eu-west-1c\"
}"
