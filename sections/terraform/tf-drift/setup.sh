#!/bin/bash
# Apply a VPC, a subnet, a security group (HTTPS only) and a t3.micro instance. Then, outside Terraform:
# resize the instance to t3.large (to keep) and open SSH to the world on the group (to revert).
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_VPC name=$STICK_CANARY_NAME
mkdir -p "$STICK_WORKSPACE/app"
cat > "$STICK_WORKSPACE/app/main.tf" <<TF
$TF_HEADER

data "aws_ami" "linux" {
  most_recent = true
  owners      = ["amazon"]
}

resource "aws_vpc" "main" {
  cidr_block = "$net.0.0/16"
  tags       = { Name = "$name" }
}

resource "aws_subnet" "app" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "$net.1.0/24"
  availability_zone = "eu-west-1a"
  tags              = { Name = "$name-app" }
}

resource "aws_security_group" "web" {
  name        = "$name-web"
  description = "web"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
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
  subnet_id              = aws_subnet.app.id
  vpc_security_group_ids = [aws_security_group.web.id]
  tags                   = { Name = "$name" }

  lifecycle {
    ignore_changes = [ami]
  }
}
TF
tf app init -input=false >/dev/null
tf app apply -auto-approve -input=false -no-color | tail -n 2
toolbox_run . bash -euo pipefail -s <<'SCRIPT'
name=$STICK_CANARY_NAME
inst=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$name" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)
aws ec2 modify-instance-attribute --instance-id "$inst" --instance-type Value=t3.large
group=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$name-web" \
    --query 'SecurityGroups[0].GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp --port 22 --cidr 0.0.0.0/0 >/dev/null
SCRIPT
