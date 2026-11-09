"""Unit tests for the config-retrieval checks (sections, NETCONF XML) and task requirements."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_on_a_stick import paths, tasks
from llm_on_a_stick.grading import validate
from llm_on_a_stick.grading.checks.retrieval import config_section, load_netconf_xml
from llm_on_a_stick.grading.labstate import NO_LAB
from test_grading import FakeLab, check, make_ctx

SRL_FLAT = """set / interface ethernet-1/1 description "to frr1"
set / network-instance default protocols bgp admin-state enable
set / network-instance default protocols bgp autonomous-system 65002
set / network-instance default protocols bgp neighbor 10.0.2.1 peer-as 65101
set / network-instance default protocols bgp-vpn bgp-instance 1
set / system name host-name srl2
"""

FRR = """frr version 10.7.1_git
hostname frr1
!
interface eth1
 ip address 10.0.1.1/31
exit
!
router bgp 65101
 neighbor 10.0.1.0 remote-as 65001
 !
 address-family ipv4 unicast
  redistribute connected
 exit-address-family
exit
!
end
"""

REPLY = """<?xml version="1.0" encoding="UTF-8"?>
<rpc-reply message-id="1" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <data>
    <interface xmlns="urn:nokia.com:srlinux:chassis:interfaces">
      <name>ethernet-1/1</name><description>stick-abc12345</description>
    </interface>
    <network-instance xmlns="urn:nokia.com:srlinux:net-inst:network-instance">
      <name>default</name>
      <interface><name>ethernet-1/1.0</name></interface>
      <protocols><bgp xmlns="urn:nokia.com:srlinux:bgp:bgp">
        <autonomous-system>65001</autonomous-system>
        <neighbor><peer-address>10.0.1.3</peer-address><peer-as>65102</peer-as></neighbor>
      </bgp></protocols>
    </network-instance>
  </data>
</rpc-reply>"""


# --------------------------------------------------------------------------- sections


def test_config_section_srlinux_prefix_excludes_lookalikes() -> None:
    section = config_section(SRL_FLAT, "srlinux", "set / network-instance default protocols bgp ")
    assert len(section.splitlines()) == 3
    assert "bgp-vpn" not in section


def test_config_section_frr_block() -> None:
    section = config_section(FRR, "frr", "router bgp").splitlines()
    assert section[0] == "router bgp 65101"
    assert section[-1] == "exit"
    assert " exit-address-family" in section
    assert "interface eth1" not in section


def test_file_matches_config_section(tmp_path: Path) -> None:
    lab = FakeLab()
    lab.configs["frr1"] = FRR
    ctx = make_ctx(tmp_path, lab)
    out = ctx.run.workspace / "bgp.cfg"

    out.write_text(config_section(FRR, "frr", "router bgp"))
    assert (
        check(ctx, "file_matches_config_section", node="frr1", path="bgp.cfg", section="router bgp").status
        == "pass"
    )

    out.write_text(FRR)  # the whole config: unfiltered
    r = check(ctx, "file_matches_config_section", node="frr1", path="bgp.cfg", section="router bgp")
    assert (r.status, r.hints) == ("fail", ["unfiltered-output"])

    out.write_text(config_section(FRR, "frr", "router bgp") + "\n neighbor 9.9.9.9 remote-as 1\n")
    r = check(ctx, "file_matches_config_section", node="frr1", path="bgp.cfg", section="router bgp")
    assert r.hints == ["hallucinated-value"]


# --------------------------------------------------------------------------- NETCONF XML


def test_load_netconf_xml_variants() -> None:
    assert load_netconf_xml(REPLY).tag == "rpc-reply"
    data_only = REPLY.split("<data>", 1)[1].rsplit("</data>", 1)[0]
    assert load_netconf_xml(f"<data>{data_only}</data>").tag == "data"
    session_dump = (
        "<hello><capabilities/></hello>\n]]>]]>\n" + REPLY + "\n]]>]]>\n<rpc-reply><ok/></rpc-reply>\n]]>]]>"
    )
    assert load_netconf_xml(session_dump).find("data") is not None
    chunked = "\n#4096\n" + REPLY + "\n##\n"
    assert load_netconf_xml(chunked).tag == "rpc-reply"
    with pytest.raises(ValueError):
        load_netconf_xml("% Invalid input detected")


def test_xml_file_xpath(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, canary={"d": "stick-abc12345"})
    (ctx.run.workspace / "r.xml").write_text(REPLY)
    expect = {
        ".//interface[name='ethernet-1/1']/description": "{{ canaries.d }}",
        ".//network-instance[name='default']/protocols/bgp/autonomous-system": "65001",
        ".//neighbor[peer-address='10.0.1.3']/peer-as": 65102,
        ".//system": "*",
    }
    r = check(ctx, "xml_file_xpath", path="r.xml", expect=expect)
    assert r.status == "fail"  # only .//system is missing
    assert list(r.observed) == [".//system"]
    assert r.hints == ["truncated-output"]
    del expect[".//system"]
    assert check(ctx, "xml_file_xpath", path="r.xml", expect=expect).status == "pass"
    wrong = check(ctx, "xml_file_xpath", path="r.xml", expect={".//autonomous-system": "64999"})
    assert wrong.hints == ["hallucinated-value"]
    (ctx.run.workspace / "bad.xml").write_text("<rpc-reply><data>")
    assert check(ctx, "xml_file_xpath", path="bad.xml", expect=expect).hints == ["wrong-format"]


def test_xml_file_absent(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    (ctx.run.workspace / "r.xml").write_text(REPLY)
    r = check(ctx, "xml_file_absent", path="r.xml", xpaths=[".//interface", ".//system"])
    assert (r.status, r.hints, r.observed) == ("fail", ["unfiltered-output"], {".//interface": 2})
    assert check(ctx, "xml_file_absent", path="r.xml", xpaths=[".//system", ".//acl"]).status == "pass"


def test_json_nested_objects_ignore_key_order(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    (ctx.run.workspace / "a.json").write_text('{"x": {"b": 2, "a": [3, 1]}}')
    assert (
        check(ctx, "json_file_matches", path="a.json", expected={"x": {"a": [1, 3], "b": "2"}}).status
        == "pass"
    )


# --------------------------------------------------------------------------- requirements & built-in tasks


def test_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    task = tasks.Task(
        id="t", section="cfg-mgmt", title="ttt", tier="basic", prompt="p" * 10, checks=[],
        requires={"devices": ["frr1", "nope"], "services": ["oxidized", "unknown"]},
    )  # fmt: skip
    monkeypatch.setattr(validate.lifecycle, "healthy", lambda spec: False)
    problems = validate.check_requirements(task, FakeLab())  # type: ignore[arg-type]
    assert any("'nope'" in p for p in problems)
    assert any("stick svc up oxidized" in p for p in problems)
    assert any("unknown service 'unknown'" in p for p in problems)
    assert not any("frr1" in p for p in problems)


def test_builtin_tasks_are_complete() -> None:
    found = tasks.discover([paths.sections_dir()])
    assert len(found) >= 5
    per_section: dict[str, int] = {}
    for path in found:
        task = tasks.load_task(path)
        per_section[task.section] = per_section.get(task.section, 0) + 1
        assert task.oracle, f"{task.id} has no oracle"
        assert task.canaries, f"{task.id} plants no canary"
        if task.topology != NO_LAB:  # a task without lab devices has no router to leave alone
            assert any(c.type == "no_change_outside" for c in task.checks), f"{task.id}: no change check"
        if any("path" in c.params for c in task.checks):  # the agent writes a file: say where
            assert "{{ workspace }}" in task.prompt or "{{workspace}}" in task.prompt, task.id
        services = task.requires.get("services") or []
        # Source-of-truth tasks start from the seed and check that nothing else changed there.
        # The same for the emulated AWS account (moto), whose check is aws_unchanged.
        for sot, unchanged in (
            ("netbox", "netbox"), ("nautobot", "nautobot"), ("moto", "aws"), ("librenms", "librenms"),
        ):  # fmt: skip
            if sot in services:
                assert sot in task.reset_services, f"{task.id} doesn't reset {sot}"
                assert any(c.type == f"{unchanged}_unchanged" for c in task.checks), (
                    f"{task.id}: no {sot} check"
                )
        assert set(task.reset_services) <= set(services), f"{task.id} resets a service it doesn't require"
    # Every attempt costs minutes on a local model: at most 5 tasks per section, i.e. per tool or group such
    # as netbox or cfg-mgmt (docs/tasks.md).
    assert max(per_section.values()) <= 5, per_section
    # One cheap floor task per section (docs/tasks.md); CI validates it on every change to shared code.
    floors = [load.section for load in map(tasks.load_task, found) if load.floor]
    assert sorted(floors) == sorted(per_section), f"floor tasks per section: {floors}"
