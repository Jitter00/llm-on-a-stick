#!/bin/bash
# Adopt the new instance type in the configuration; apply then only removes the extra rule.
set -euo pipefail
source "$STICK_LIB/common.sh"
sed -i 's/"t3.micro"/"t3.large"/' "$STICK_WORKSPACE/app/main.tf"
tf app apply -auto-approve -input=false -no-color | tail -n 2
