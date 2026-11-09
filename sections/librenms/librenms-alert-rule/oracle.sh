#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
condition() { jq -n --arg f "$1" --arg v "$2" \
    '{id: $f, field: $f, type: "string", input: "text", operator: "equal", value: $v}'; }
rule=$(jq -n --arg n "$STICK_CANARY_RULE" --argjson a "$(condition ports.ifAlias "$STICK_CANARY_DESC")" \
    --argjson b "$(condition ports.ifOperStatus down)" \
    '{name: $n, devices: [-1], severity: "critical", count: 1, delay: 0, interval: 300, mute: false,
      builder: {condition: "AND", rules: [$a, $b], valid: true}}')
# LibreNMS 26.10 creates the rule and still answers with an error about transports: check what exists.
librenms_api POST rules "$rule" >/dev/null 2>&1 || true
librenms_api GET rules | jq -e --arg n "$STICK_CANARY_RULE" '[.rules[] | select(.name == $n)] | length == 1' >/dev/null
