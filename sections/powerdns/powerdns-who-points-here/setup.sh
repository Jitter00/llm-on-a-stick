#!/bin/bash
# Two zones. The address has an A record in each, and one alias; next to them a neighbouring address, a TXT
# record that only mentions the address, and an alias of another name.
set -euo pipefail
source "$STICK_LIB/common.sh"
addr=$STICK_CANARY_ADDR
near="${addr%.*}.$(( ${addr##*.} % 254 + 1 ))"  # the same network, another host
pdns_zone stick.lab.
pdns_zone oob.example.
pdns_rrset stick.lab. ns1.stick.lab. A 3600 198.18.255.53
pdns_rrset stick.lab. "$STICK_CANARY_WEB.stick.lab." A 300 "$addr"
pdns_rrset stick.lab. "$STICK_CANARY_ALIAS.stick.lab." CNAME 300 "$STICK_CANARY_WEB.stick.lab."
pdns_rrset stick.lab. "$STICK_CANARY_NEAR.stick.lab." A 300 "$near"
pdns_rrset stick.lab. "$STICK_CANARY_NOTE.stick.lab." TXT 300 "\"moved away from $addr\""
pdns_rrset stick.lab. "$STICK_CANARY_FAR.stick.lab." A 300 "$STICK_CANARY_OTHER"
pdns_rrset stick.lab. "www-$STICK_CANARY_FAR.stick.lab." CNAME 300 "$STICK_CANARY_FAR.stick.lab."
pdns_rrset oob.example. "$STICK_CANARY_OOB.oob.example." A 300 "$addr"
pdns_rrset oob.example. "$STICK_CANARY_FAR.oob.example." A 300 "$STICK_CANARY_OTHER"
