#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
id() { aws_cli ec2 "$1" --filters "$2" --query "$3" --output text; }
vpc=$(id describe-vpcs "Name=tag:Name,Values=$name" 'Vpcs[0].VpcId')
subnet=$(id describe-subnets "Name=tag:Name,Values=$name-a" 'Subnets[0].SubnetId')
group=$(id describe-security-groups "Name=group-name,Values=$name-web" 'SecurityGroups[0].GroupId')
igw=$(id describe-internet-gateways "Name=tag:Name,Values=$name" 'InternetGateways[0].InternetGatewayId')
rtb=$(id describe-route-tables "Name=tag:Name,Values=$name-public" 'RouteTables[0].RouteTableId')
cat >> "$STICK_WORKSPACE/legacy/main.tf" <<TF

import {
  to = aws_internet_gateway.main
  id = "$igw"
}

import {
  to = aws_route_table.public
  id = "$rtb"
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "$name", owner = "netops" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "$name-public", owner = "netops" }

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

import {
  to = aws_vpc.main
  id = "$vpc"
}

import {
  to = aws_subnet.a
  id = "$subnet"
}

import {
  to = aws_security_group.web
  id = "$group"
}

resource "aws_vpc" "main" {
  cidr_block           = "$net.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "$name", owner = "netops" }
}

resource "aws_subnet" "a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "$net.1.0/24"
  availability_zone       = "eu-west-1b"
  map_public_ip_on_launch = true
  tags                    = { Name = "$name-a", owner = "netops" }
}

resource "aws_security_group" "web" {
  name        = "$name-web"
  description = "web tier, made by hand"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol    = "tcp"
    from_port   = 8080
    to_port     = 8080
    cidr_blocks = ["$net.0.0/16"]
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}
TF
tf legacy init -input=false >/dev/null
tf legacy apply -auto-approve -input=false -no-color | tail -n 2
