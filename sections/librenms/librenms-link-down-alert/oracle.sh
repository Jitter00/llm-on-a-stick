#!/bin/bash
# Reference solution: add srl2, then one rule: enabled, not up, and described as leading to another router.
set -euo pipefail
source "$STICK_LIB/common.sh"
librenms_add_device "$STICK_NODE_SRL2_IP" stick-ro >/dev/null
condition() { jq -n --arg f "$1" --arg o "$2" --arg v "$3" \
    '{id: $f, field: $f, type: "string", input: "text", operator: $o, value: $v}'; }
rule=$(jq -n --arg n "$STICK_CANARY_RULE" \
    --argjson a "$(condition ports.ifAdminStatus equal up)" \
    --argjson b "$(condition ports.ifOperStatus not_equal up)" \
    --argjson c "$(condition ports.ifAlias begins_with "to ")" \
    '{name: $n, devices: [-1], severity: "critical", count: 1, delay: 0, interval: 300, mute: false,
      builder: {condition: "AND", rules: [$a, $b, $c], valid: true}}')
# LibreNMS 26.10 creates the rule and still answers with an error about transports: check what exists.
librenms_api POST rules "$rule" >/dev/null 2>&1 || true
librenms_api GET rules | jq -e --arg n "$STICK_CANARY_RULE" '[.rules[] | select(.name == $n)] | length == 1' >/dev/null
