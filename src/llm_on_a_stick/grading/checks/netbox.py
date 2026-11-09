"""NetBox checks beyond `netbox_object`: nothing else in NetBox changed."""

from __future__ import annotations

import json

from llm_on_a_stick.grading import netboxstate
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext

SAMPLE = 10


@check("netbox_unchanged")
def netbox_unchanged(ctx: GradeContext, allow_new: list[str] | None = None) -> Verdict:
    """NetBox matches its state at `stick task start` (baseline/netbox.json): nothing changed or deleted, and
    nothing added except on the `allow_new` endpoints (e.g. [dcim/devices, ipam/ip-addresses])."""
    path = ctx.run.baseline_dir / "netbox.json"
    if not path.exists():
        return Verdict(
            "error", "no NetBox baseline: the task must list netbox under requires.services",
            hints=["env-error"],
        )  # fmt: skip
    before: netboxstate.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    after = netboxstate.snapshot(ctx.services.netbox(), tuple(before))
    problems = netboxstate.diff(before, after, allow_new or [])
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected={"allow_new": allow_new or []}, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "nothing else changed in NetBox")
