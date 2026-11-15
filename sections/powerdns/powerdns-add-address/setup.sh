#!/bin/bash
# The service name with one address (TTL 900) and its PTR record, a database host next to it, and a second
# forward zone in which the same host name exists with another address.
set -euo pipefail
source "$STICK_LIB/common.sh"
net="198.19.$STICK_CANARY_THIRD"
rev="$STICK_CANARY_THIRD.19.198.in-addr.arpa."
pdns_zone stick.lab.
pdns_zone stick.example.
pdns_zone "$rev"
pdns_rrset stick.lab. ns1.stick.lab. A 3600 198.18.255.53
pdns_rrset stick.lab. "$STICK_CANARY_SVC.stick.lab." A 900 "$net.10"
pdns_rrset stick.lab. "$STICK_CANARY_DB.stick.lab." A 300 "$net.11"
pdns_rrset stick.example. "$STICK_CANARY_SVC.stick.example." A 300 203.0.113.10
pdns_rrset "$rev" "10.$rev" PTR 3600 "$STICK_CANARY_SVC.stick.lab."
pdns_rrset "$rev" "11.$rev" PTR 3600 "$STICK_CANARY_DB.stick.lab."
