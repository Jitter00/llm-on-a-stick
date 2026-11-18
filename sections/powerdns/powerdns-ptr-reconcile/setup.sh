#!/bin/bash
# Two forward zones and the two reverse zones of 198.19.T1.0/24 and 198.19.T2.0/24. What the reverse zones
# lack or get wrong:
#   - svc.stick.lab has two addresses (T1.10, T1.11): only the first has a PTR record;
#   - db.stick.lab (T1.20): its PTR record still names the host's old name;
#   - T1.60: a PTR record to a name that no longer exists anywhere;
#   - web.stick.lab (T2.30): no PTR record; www.stick.lab is a CNAME to it (an alias gets no PTR record);
#   - mgmt.oob.example (T2.50), in the other forward zone: no PTR record;
#   - mail.stick.lab (T2.40): right, and stays as it is.
# oob.example also has an address outside both networks (no reverse zone here covers it).
set -euo pipefail
source "$STICK_LIB/common.sh"
n1="198.19.$STICK_CANARY_T1" n2="198.19.$STICK_CANARY_T2"
r1="$STICK_CANARY_T1.19.198.in-addr.arpa." r2="$STICK_CANARY_T2.19.198.in-addr.arpa."
svc=$STICK_CANARY_SVC db=$STICK_CANARY_DB web=$STICK_CANARY_WEB mail=$STICK_CANARY_MAIL mgmt=$STICK_CANARY_MGMT
pdns_zone stick.lab.
pdns_zone oob.example.
pdns_zone "$r1"
pdns_zone "$r2"
pdns_rrset stick.lab. ns1.stick.lab. A 3600 198.18.255.53
pdns_rrset stick.lab. "$svc.stick.lab." A 300 "$n1.10" "$n1.11"
pdns_rrset stick.lab. "$db.stick.lab." A 300 "$n1.20"
pdns_rrset stick.lab. "$web.stick.lab." A 300 "$n2.30"
pdns_rrset stick.lab. "www.stick.lab." CNAME 300 "$web.stick.lab."
pdns_rrset stick.lab. "$mail.stick.lab." A 300 "$n2.40"
pdns_rrset stick.lab. "$mail.stick.lab." TXT 300 "\"was $n1.60\""
pdns_rrset oob.example. "$mgmt.oob.example." A 300 "$n2.50"
pdns_rrset oob.example. "bastion.oob.example." A 300 203.0.113.7
pdns_rrset "$r1" "10.$r1" PTR 3600 "$svc.stick.lab."
pdns_rrset "$r1" "20.$r1" PTR 3600 "$STICK_CANARY_OLD.stick.lab."
pdns_rrset "$r1" "60.$r1" PTR 3600 "$STICK_CANARY_GONE.stick.lab."
pdns_rrset "$r2" "40.$r2" PTR 3600 "$mail.stick.lab."
