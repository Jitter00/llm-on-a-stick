#!/bin/bash
# Reference solution: a real NETCONF session (hello, get-config running, close) over SSH port 830.
set -euo pipefail
source "$STICK_LIB/common.sh"
netconf_get_config "$STICK_NODE_SRL1_IP" > "$STICK_WORKSPACE/srl1-running.xml"
