#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
down=$(librenms_api GET devices | jq -er '.devices[] | select(.status == 0) | .hostname')
librenms_api PATCH "devices/$down" "$(jq -n --arg c "$STICK_CANARY_COMMUNITY" '{field: "community", data: $c}')" >/dev/null
