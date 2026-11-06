import json

from llm_on_a_stick.env import containerlab


def test_parse_inspect_lab_keyed_format() -> None:
    raw = json.dumps(
        {
            "stick-base": [
                {
                    "name": "clab-stick-base-srl1",
                    "kind": "nokia_srlinux",
                    "image": "ghcr.io/nokia/srlinux:26.7.2",
                    "state": "running",
                    "ipv4_address": "172.30.30.11/24",
                }
            ]
        }
    )
    nodes = containerlab.parse_inspect(raw)
    assert len(nodes) == 1
    assert nodes[0].name == "clab-stick-base-srl1"
    assert nodes[0].mgmt_ipv4 == "172.30.30.11/24"


def test_parse_inspect_legacy_containers_format() -> None:
    raw = json.dumps({"containers": [{"name": "n1", "kind": "linux", "image": "x", "state": "running"}]})
    assert [n.name for n in containerlab.parse_inspect(raw)] == ["n1"]


def test_parse_inspect_empty() -> None:
    assert containerlab.parse_inspect("") == []
