"""PowerDNS for grading: what its DNS port answers, a snapshot of its zones and records, and what changed
since.

`stick task start` saves the snapshot to baseline/powerdns.json right after setup; the `powerdns_unchanged`
check compares it with the service at grading time. Records are compared as record sets (a name and a type),
the way PowerDNS's API changes them.
"""

from __future__ import annotations

from typing import Any, Protocol

import dns.exception
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype

from llm_on_a_stick import lab
from llm_on_a_stick.grading.librenmsstate import diff as diff  # the same rules: kind / kind:label allow lists

SERVICE = "powerdns"
SERVER = "servers/localhost"
ZONE_FIELDS = ("kind", "dnssec", "account")
# A zone's SOA holds its serial, which PowerDNS may raise with every change: not compared.
SKIPPED_TYPES = ("SOA",)

Snapshot = dict[str, dict[str, dict[str, Any]]]  # kind (zones, rrsets) -> key -> object


class Api(Protocol):
    def get(self, path: str) -> Any: ...


class DnsError(RuntimeError):
    pass


def fqdn(name: str) -> str:
    """Lower case with the trailing dot, as PowerDNS stores names."""
    return name.strip().lower().rstrip(".") + "."


def dns_port() -> int:
    """The host port of this lab instance's PowerDNS (DNS over UDP and TCP)."""
    key = "STICK_DNS_PORT"
    return int(lab.env().get(key) or lab.PORTS[key])


def resolve(
    name: str, rtype: str, port: int | None = None, timeout: float = 5
) -> tuple[list[str], int | None]:
    """Ask PowerDNS itself (a DNS query, not its API): the answer's values for `name` and `rtype`, sorted, and
    their TTL. No such name or no record of that type: ([], None). Names in answers are lower case, with the
    trailing dot. A CNAME is not followed: an A query for an alias returns nothing."""
    query = dns.message.make_query(fqdn(name), rtype)
    try:
        reply = dns.query.udp(query, "127.0.0.1", port=port or dns_port(), timeout=timeout)
    except (dns.exception.DNSException, OSError) as exc:
        raise DnsError(f"no DNS answer from PowerDNS for {name} {rtype}: {exc}") from exc
    if reply.rcode() not in (dns.rcode.NOERROR, dns.rcode.NXDOMAIN):
        raise DnsError(f"PowerDNS answered {dns.rcode.to_text(reply.rcode())} for {name} {rtype}")
    wanted = dns.rdatatype.from_text(rtype)
    for rrset in reply.answer:
        if rrset.rdtype == wanted and rrset.name.to_text().lower() == fqdn(name):
            return sorted(r.to_text().lower() for r in rrset), rrset.ttl
    return [], None


def zones(api: Api) -> list[dict[str, Any]]:
    return list(api.get(f"{SERVER}/zones") or [])


def rrsets(api: Api, zone: str) -> list[dict[str, Any]]:
    """The zone's record sets: `name`, `type`, `ttl`, `records` ({content, disabled})."""
    return list((api.get(f"{SERVER}/zones/{fqdn(zone)}") or {}).get("rrsets") or [])


def snapshot(api: Api) -> Snapshot:
    snap: Snapshot = {"zones": {}, "rrsets": {}}
    for zone in zones(api):
        name = zone["name"]
        snap["zones"][name] = {"label": name, **{k: zone.get(k) for k in ZONE_FIELDS}}
        for rrset in rrsets(api, name):
            if rrset["type"] in SKIPPED_TYPES:
                continue
            key = f"{rrset['name']}/{rrset['type']}"
            records = sorted([r["content"], bool(r.get("disabled"))] for r in rrset.get("records") or [])
            snap["rrsets"][key] = {"label": key, "ttl": rrset.get("ttl"), "records": records}
    return snap
