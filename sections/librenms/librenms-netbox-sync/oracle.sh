#!/bin/bash
set -euo pipefail
source "$STICK_LIB/common.sh"
monitored=$(librenms_api GET devices | jq -r '.devices[].hostname')
for ip in $(netbox_api GET "dcim/devices/?status=active&limit=0" | jq -r '.results[].primary_ip4.address | split("/")[0]'); do
    grep -qxF "$ip" <<<"$monitored" && continue
    librenms_api POST devices "$(jq -n --arg h "$ip" '{hostname: $h, version: "v2c", community: "stick-ro"}')" >/dev/null
done
