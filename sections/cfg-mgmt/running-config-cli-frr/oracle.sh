#!/bin/bash
# Reference solution: what a correct agent does over SSH (same output as `ssh admin@frr2 "show running-config"`).
set -euo pipefail
source "$STICK_LIB/common.sh"
frr_cli "$STICK_NODE_FRR2" "show running-config" > "$STICK_WORKSPACE/frr2.cfg"
