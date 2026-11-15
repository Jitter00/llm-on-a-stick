"""The PowerDNS service by itself (no lab): it starts without zones, its DNS port answers what the API
wrote, a reset takes the zones away again, and the MCP server made from its API description reads them.

Run with: uv run pytest -m lab tests/integration/test_powerdns.py
"""

from __future__ import annotations

import urllib.request
from collections.abc import Iterator

import pytest
from labutil import check_mcp_server, service_session

from llm_on_a_stick import paths, services
from llm_on_a_stick.grading import powerdnsstate as state
from llm_on_a_stick.grading.run import rest_client
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.seed import RestClient

pytestmark = pytest.mark.lab

ZONE = "stick.lab."
NEW_ZONE = {"name": ZONE, "kind": "Native", "nameservers": ["ns1.stick.lab."]}


def rrset(name: str, rtype: str, *records: tuple[str, bool]) -> dict[str, object]:
    contents = [{"content": c, "disabled": d} for c, d in records]
    return {
        "rrsets": [{"name": name, "type": rtype, "ttl": 300, "changetype": "REPLACE", "records": contents}]
    }


@pytest.fixture(scope="module")
def powerdns() -> Iterator[RestClient]:
    with service_session("powerdns") as spec:
        lifecycle.restore_snapshot(spec)  # start from the baseline, whatever an earlier run left behind
        yield rest_client("powerdns")
        lifecycle.restore_snapshot(spec)


def test_it_starts_without_zones(powerdns: RestClient) -> None:
    assert state.snapshot(powerdns) == {"zones": {}, "rrsets": {}}


def test_the_image_has_the_api_description_this_powerdns_serves(powerdns: RestClient) -> None:
    spec = services.load("powerdns")
    assert spec.api_settings is not None
    url = spec.health.url.split("/api/")[0] + "/api/docs"
    req = urllib.request.Request(url, headers=spec.api_settings.headers)  # noqa: S310
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        served = resp.read()
    assert served == (paths.image_dir("mcp") / "powerdns-api.yaml").read_bytes()


def test_dns_answers_what_the_api_wrote_and_reset_takes_it_away(powerdns: RestClient) -> None:
    powerdns.post("servers/localhost/zones", NEW_ZONE)
    before = state.snapshot(powerdns)
    path = f"servers/localhost/zones/{ZONE}"
    powerdns.request(
        "PATCH", path, rrset("web.stick.lab.", "A", ("198.19.7.20", False), ("198.19.7.10", False))
    )
    powerdns.request("PATCH", path, rrset("off.stick.lab.", "A", ("198.19.7.30", True)))
    powerdns.request("PATCH", path, rrset("www.stick.lab.", "CNAME", ("web.stick.lab.", False)))
    assert state.resolve("web.stick.lab", "A") == (["198.19.7.10", "198.19.7.20"], 300)
    assert state.resolve("WWW.stick.lab.", "CNAME") == (["web.stick.lab."], 300)
    assert state.resolve("off.stick.lab", "A") == ([], None)  # disabled: in the API, not in DNS
    assert state.resolve("nosuch.stick.lab", "A") == ([], None)
    assert sorted(state.diff(before, state.snapshot(powerdns), [], [], [])) == [
        "rrsets: added off.stick.lab./A",
        "rrsets: added web.stick.lab./A",
        "rrsets: added www.stick.lab./CNAME",
    ]

    lifecycle.restore_snapshot(services.load("powerdns"))
    assert state.snapshot(powerdns) == {"zones": {}, "rrsets": {}}


def test_mcp_server_lists_the_zones(powerdns: RestClient) -> None:
    powerdns.post("servers/localhost/zones", NEW_ZONE)
    check_mcp_server("powerdns", "listZones", {"server_id": "localhost"}, '"name":"stick.lab."')
