"""Checks for config-retrieval tasks: one section of a config, and NETCONF XML replies."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from llm_on_a_stick.grading import configdiff
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.checks.builtin import SAMPLE, _no_output, _read_output
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.grading.results import FailureHint

# --------------------------------------------------------------------------- config sections


def config_section(text: str, os_: str, section: str) -> str:
    """The part of a config that belongs to `section`.

    SR Linux flat config: every line starting with `section`
    (e.g. "set / network-instance default protocols bgp").
    FRR: the block whose first line starts with `section` (e.g. "router bgp"), up to and including
    its top-level "exit".
    """
    lines = text.splitlines()
    if os_ == "srlinux":
        return "\n".join(line for line in lines if " ".join(line.split()).startswith(section))
    out: list[str] = []
    inside = False
    for line in lines:
        if not inside and line.startswith(section):
            inside = True
        if inside:
            out.append(line)
            if line.rstrip() == "exit":
                inside = False
    return "\n".join(out)


@check("file_matches_config_section")
def file_matches_config_section(ctx: GradeContext, node: str, path: str, section: str) -> Verdict:
    """The file holds exactly one section of the node's running config (flat format on SR Linux)."""
    text = _read_output(ctx, path)
    if text is None:
        return _no_output(path)
    os_ = ctx.lab.nodes()[node].os
    full = ctx.lab.running_config(node, "flat")
    expected = configdiff.normalise(config_section(full, os_, section), os_)
    output = configdiff.normalise(text, os_)
    diff = configdiff.compare(expected, output)
    summary = {"section_lines": diff.expected_lines, "output_lines": diff.observed_lines}
    if diff.identical:
        return Verdict(
            "pass",
            f"{path} matches {node}'s '{section}' section ({diff.expected_lines} lines)",
            observed=summary,
        )

    device_lines = set(configdiff.normalise(full, os_))
    from_elsewhere = [line for line in diff.extra if line in device_lines]
    invented = [line for line in diff.extra if line not in device_lines]
    hints: list[FailureHint] = []
    if diff.overlap < 0.2:
        hints.append("wrong-format")
    if from_elsewhere:
        hints.append("unfiltered-output")
    if invented:
        hints.append("hallucinated-value")
    if diff.missing and not diff.extra:
        hints.append("truncated-output")
    observed = {
        **summary,
        "missing_count": len(diff.missing),
        "from_other_sections_count": len(from_elsewhere),
        "invented_count": len(invented),
        "missing_sample": diff.missing[:SAMPLE],
        "from_other_sections_sample": from_elsewhere[:SAMPLE],
        "invented_sample": invented[:SAMPLE],
    }
    message = (
        f"{len(diff.missing)} of {diff.expected_lines} section lines missing, "
        f"{len(from_elsewhere)} lines from other sections, {len(invented)} lines not on the device"
    )
    return Verdict("fail", message, expected=f"{node} '{section}' section", observed=observed, hints=hints)


# --------------------------------------------------------------------------- NETCONF / XML

_FRAME_LINE = re.compile(r"^\s*(#\d+|##)\s*$", re.MULTILINE)  # NETCONF 1.1 chunk headers


def _strip_namespaces(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        el.attrib = {k.split("}", 1)[-1]: v for k, v in el.attrib.items()}
    return root


def load_netconf_xml(text: str) -> ET.Element:
    """Parse what an agent saved: a bare <data>, an <rpc-reply>, or a raw session dump with framing.

    For a session dump, the first <rpc-reply> that carries <data> is used. Namespaces are dropped, so
    task authors write plain paths like `.//interface[name='ethernet-1/1']/description`.
    """
    candidates = [text]
    if "]]>]]>" in text or _FRAME_LINE.search(text):
        cleaned = _FRAME_LINE.sub("", text)
        candidates = [part.strip() for part in cleaned.split("]]>]]>") if "<data" in part] or candidates
    errors = []
    for candidate in candidates:
        body = re.sub(r"^\s*<\?xml[^>]*\?>", "", candidate.strip())
        try:
            return _strip_namespaces(ET.fromstring(body))  # noqa: S314 (local lab output)
        except ET.ParseError as exc:
            errors.append(str(exc))
    raise ValueError("; ".join(errors) or "no XML found")


def _find_texts(root: ET.Element, xpath: str) -> list[str]:
    # Allow absolute-looking paths: ElementTree only supports relative ones.
    path = xpath if xpath.startswith(".") else "." + xpath if xpath.startswith("/") else ".//" + xpath
    return [(el.text or "").strip() for el in root.findall(path)]


def _xml_or_fail(ctx: GradeContext, path: str) -> ET.Element | Verdict:
    text = _read_output(ctx, path)
    if text is None:
        return _no_output(path)
    try:
        return load_netconf_xml(text)
    except (ValueError, SyntaxError) as exc:
        return Verdict("fail", f"{path} is not a usable XML reply: {exc}"[:300], hints=["wrong-format"])


@check("xml_file_xpath")
def xml_file_xpath(ctx: GradeContext, path: str, expect: dict[str, Any]) -> Verdict:
    """Each XPath (ElementTree subset, no namespaces) finds an element with that text ("*" = exists)."""
    root = _xml_or_fail(ctx, path)
    if isinstance(root, Verdict):
        return root
    wrong: dict[str, Any] = {}
    for xpath, want in expect.items():
        found = _find_texts(root, xpath)
        ok = bool(found) if want == "*" else str(want).strip() in found
        if not ok:
            wrong[xpath] = found[:SAMPLE] or "<not found>"
    if wrong:
        # Elements missing entirely: the reply was cut short or the wrong data was requested.
        # Elements present with other values: the values don't come from this device.
        missing_only = all(v == "<not found>" for v in wrong.values())
        hint: FailureHint = "truncated-output" if missing_only else "hallucinated-value"
        return Verdict(
            "fail", f"{len(wrong)} of {len(expect)} XML values wrong or missing",
            expected=expect, observed=wrong, hints=[hint],
        )  # fmt: skip
    return Verdict("pass", f"all {len(expect)} XML values correct")


@check("xml_file_absent")
def xml_file_absent(ctx: GradeContext, path: str, xpaths: list[str]) -> Verdict:
    """None of the XPaths match: used to prove a NETCONF filter was really applied."""
    root = _xml_or_fail(ctx, path)
    if isinstance(root, Verdict):
        return root
    present = {xp: len(root.findall(xp if xp.startswith(".") else ".//" + xp.lstrip("/"))) for xp in xpaths}
    present = {xp: n for xp, n in present.items() if n}
    if present:
        return Verdict(
            "fail", f"reply contains data that should have been filtered out: {', '.join(present)}",
            expected={"absent": xpaths}, observed=present, hints=["unfiltered-output"],
        )  # fmt: skip
    return Verdict("pass", "no unwanted data in the reply")
