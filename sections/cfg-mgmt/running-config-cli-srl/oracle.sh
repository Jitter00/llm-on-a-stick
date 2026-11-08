#!/bin/bash
# Reference solution: `info flat` from the root context (same output as over SSH).
set -euo pipefail
source "$STICK_LIB/common.sh"
srl_cli "$STICK_NODE_SRL1" "info flat" > "$STICK_WORKSPACE/srl1.cfg"
