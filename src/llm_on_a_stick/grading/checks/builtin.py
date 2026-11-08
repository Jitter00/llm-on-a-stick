"""Built-in checks. Each returns a Verdict with what was expected, what was observed, and failure hints.

Parameters come from task.yaml (`checks: [{type: ..., params: {...}}]`) after `{{ ... }}` rendering.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from llm_on_a_stick.grading import configdiff
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.grading.labstate import ConfigFormat
from llm_on_a_stick.grading.results import FailureHint

SAMPLE = 5  # how many example lines to show in a result


def _read_output(ctx: GradeContext, path: str) -> str | None:
    file = ctx.workspace_file(path)
    if not file.is_file():
        return None
    text = file.read_text(encoding="utf-8", errors="replace")
    return text if text.strip() else None


def _no_output(path: str) -> Verdict:
    return Verdict("fail", f"{path} is missing or empty", expected=f"a file at {path}", hints=["no-output"])


# --------------------------------------------------------------------------- files


@check("file_exists")
def file_exists(ctx: GradeContext, path: str) -> Verdict:
    if _read_output(ctx, path) is None:
        return _no_output(path)
    return Verdict("pass", f"{path} exists")


@check("file_contains")
def file_contains(ctx: GradeContext, path: str, lines: list[str]) -> Verdict:
    """Every given line (after whitespace normalisation) appears in the file."""
    text = _read_output(ctx, path)
    if text is None:
        return _no_output(path)
    present = {" ".join(line.split()) for line in text.splitlines()}
    missing = [line for line in lines if " ".join(line.split()) not in present]
    if missing:
        return Verdict(
            "fail",
            f"{len(missing)} of {len(lines)} expected lines missing",
            expected=lines,
            observed={"missing": missing},
        )
    return Verdict("pass", f"all {len(lines)} lines present")


@check("file_matches_running_config")
def file_matches_running_config(
    ctx: GradeContext, node: str, path: str, format: ConfigFormat = "flat", ignore: list[str] | None = None
) -> Verdict:
    """The file holds the node's complete running config (order-insensitive, whitespace-normalised)."""
    text = _read_output(ctx, path)
    if text is None:
        return _no_output(path)
    os_ = ctx.lab.nodes()[node].os
    device = configdiff.normalise(ctx.lab.running_config(node, format), os_, ignore or [])
    output = configdiff.normalise(text, os_, ignore or [])
    diff = configdiff.compare(device, output)
    summary = {"device_lines": diff.expected_lines, "output_lines": diff.observed_lines}
    if diff.identical:
        return Verdict(
            "pass", f"{path} matches {node}'s running config ({diff.expected_lines} lines)", observed=summary
        )

    hints: list[FailureHint] = []
    if diff.overlap < 0.2:
        hints.append("wrong-format")
    else:
        if diff.extra:
            hints.append("hallucinated-value")
        if diff.missing and not diff.extra:
            hints.append("truncated-output")
    observed = {
        **summary,
        "missing_count": len(diff.missing),
        "extra_count": len(diff.extra),
        "missing_sample": diff.missing[:SAMPLE],
        "extra_sample": diff.extra[:SAMPLE],
    }
    message = (
        f"{len(diff.missing)} of {diff.expected_lines} device lines missing, "
        f"{len(diff.extra)} lines not on the device"
    )
    return Verdict(
        "fail", message, expected=f"{node} running config ({format})", observed=observed, hints=hints
    )


@check("json_file_matches")
def json_file_matches(ctx: GradeContext, path: str, expected: dict[str, Any]) -> Verdict:
    """The file is JSON and contains every expected key with the expected value (extra keys are fine)."""
    text = _read_output(ctx, path)
    if text is None:
        return _no_output(path)
    try:
        data = json.loads(text)
    except ValueError as exc:
        return Verdict("fail", f"{path} is not valid JSON: {exc}", expected=expected, hints=["wrong-format"])
    if not isinstance(data, dict):
        return Verdict("fail", f"{path} is not a JSON object", expected=expected, hints=["wrong-format"])

    wrong = {}
    for key, want in expected.items():
        got = data.get(key, "<missing>")
        if _normalise_json(got) != _normalise_json(want):
            wrong[key] = got
    if wrong:
        hint: FailureHint = (
            "hallucinated-value" if any(v != "<missing>" for v in wrong.values()) else "wrong-format"
        )
        return Verdict(
            "fail",
            f"{len(wrong)} of {len(expected)} values wrong",
            expected=expected,
            observed=wrong,
            hints=[hint],
        )
    return Verdict("pass", f"all {len(expected)} values correct")


def _normalise_json(value: Any) -> Any:
    """Compare loosely: numbers vs numeric strings, list order and key order don't matter."""
    if isinstance(value, dict):
        return {str(k): _normalise_json(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return sorted((_normalise_json(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, bool) or value is None:
        return value
    return str(value).strip()


# --------------------------------------------------------------------------- devices


@check("running_config_contains")
def running_config_contains(
    ctx: GradeContext, node: str, lines: list[str], format: ConfigFormat = "flat"
) -> Verdict:
    os_ = ctx.lab.nodes()[node].os
    device = set(configdiff.normalise(ctx.lab.running_config(node, format), os_))
    missing = [line for line in lines if " ".join(line.split()) not in device]
    if missing:
        return Verdict(
            "fail", f"{node}: {len(missing)} expected lines not configured", expected=lines,
            observed={"missing": missing}, hints=["incomplete-config"],
        )  # fmt: skip
    return Verdict("pass", f"{node}: all {len(lines)} lines configured")


@check("bgp_session")
def bgp_session(ctx: GradeContext, node: str, peer: str, state: str = "established") -> Verdict:
    sessions = ctx.lab.bgp_sessions(node)
    got = sessions.get(peer, "<no such neighbor>")
    if got == state.lower():
        return Verdict("pass", f"{node} -> {peer}: {got}")
    return Verdict(
        "fail", f"{node} -> {peer}: {got}", expected=state.lower(), observed=got, hints=["wrong-config"]
    )


@check("no_change_outside")
def no_change_outside(ctx: GradeContext, allowed: list[str] | None = None) -> Verdict:
    """No router outside `allowed` differs from its config at `stick task start`."""
    allowed = allowed or []
    changed: dict[str, dict[str, Any]] = {}
    for node in ctx.lab.nodes().values():
        if node.os == "host" or node.name in allowed:
            continue
        before = ctx.baseline_config(node.name)
        if before is None:
            continue
        diff = configdiff.compare(
            configdiff.normalise(before, node.os),
            configdiff.normalise(ctx.lab.running_config(node.name), node.os),
        )
        if not diff.identical:
            changed[node.name] = {
                "removed": diff.missing[:SAMPLE],
                "added": diff.extra[:SAMPLE],
                "removed_count": len(diff.missing),
                "added_count": len(diff.extra),
            }
    if changed:
        return Verdict(
            "fail", f"changed outside the allowed scope: {', '.join(changed)}",
            expected={"allowed": allowed}, observed=changed, hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "no changes outside the allowed scope", expected={"allowed": allowed})


# --------------------------------------------------------------------------- services


@check("oxidized_has_backup")
def oxidized_has_backup(
    ctx: GradeContext, node: str, min_versions: int = 1, contains: list[str] | None = None
) -> Verdict:
    nodes = {n["name"]: n for n in ctx.services.oxidized("nodes.json")}
    if node not in nodes or (nodes[node].get("last") or {}).get("status") != "success":
        status = (nodes.get(node, {}).get("last") or {}).get("status", "not in inventory")
        return Verdict(
            "fail", f"no successful Oxidized backup of {node} ({status})", hints=["missing-object"]
        )
    versions = len(ctx.services.oxidized(f"node/version.json?node_full={urllib.parse.quote(node)}"))
    if versions < min_versions:
        return Verdict(
            "fail", f"{node}: {versions} backup version(s), expected at least {min_versions}",
            expected=min_versions, observed=versions, hints=["missing-object"],
        )  # fmt: skip
    if contains:
        backup = {" ".join(line.split()) for line in ctx.services.oxidized(f"node/fetch/{node}").splitlines()}
        missing = [line for line in contains if " ".join(line.split()) not in backup]
        if missing:
            return Verdict(
                "fail", f"{node}: latest backup lacks {len(missing)} expected line(s)",
                expected=contains, observed={"missing": missing}, hints=["missing-object"],
            )  # fmt: skip
    return Verdict("pass", f"{node}: {versions} backup version(s)")


@check("netbox_object")
def netbox_object(
    ctx: GradeContext,
    endpoint: str,
    filters: dict[str, Any] | None = None,
    count: int | None = None,
    min: int = 1,
) -> Verdict:
    """Objects matching `filters` exist at `endpoint` (e.g. dcim/devices): exactly `count`, or >= `min`."""
    query = urllib.parse.urlencode(filters or {}, doseq=True)
    found = int(ctx.services.netbox().get(f"{endpoint.strip('/')}/?{query}")["count"])
    expected = {"count": count} if count is not None else {"min": min}
    ok = found == count if count is not None else found >= min
    if ok:
        return Verdict("pass", f"{endpoint}: {found} match(es)", expected=expected, observed=found)
    return Verdict(
        "fail", f"{endpoint} {filters or {}}: {found} match(es)", expected=expected, observed=found,
        hints=["missing-object"],
    )  # fmt: skip
