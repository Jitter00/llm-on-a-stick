"""PowerDNS checks: what its DNS port answers for a name, and nothing else changed."""

from __future__ import annotations

import json
from typing import Any

from llm_on_a_stick.grading import powerdnsstate as state
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.grading.results import FailureHint

SAMPLE = 10


@check("dns_record")
def dns_record(
    ctx: GradeContext,
    name: str,
    values: list[str],
    type: str = "A",
    ttl: int | None = None,
) -> Verdict:
    """A DNS query to PowerDNS for `name` and `type` is answered with exactly `values` (order doesn't matter;
    an empty list: no such record). The query goes to the DNS port, not the API, so a disabled record or one
    in the wrong zone doesn't count. Names among the values (PTR, CNAME) are compared without regard to case
    or a trailing dot. `ttl`: the answer has this TTL."""
    rtype = type.upper()
    names = rtype in ("PTR", "CNAME", "NS")
    want = sorted(state.fqdn(str(v)) if names else str(v).lower() for v in values)
    expected: dict[str, Any] = {"name": state.fqdn(name), "type": rtype, "values": want}
    if ttl is not None:
        expected["ttl"] = ttl
    try:
        got, got_ttl = state.resolve(name, rtype)
    except state.DnsError as exc:
        return Verdict("error", str(exc), expected=expected, hints=["env-error"])
    observed = {"values": got, "ttl": got_ttl}
    label = f"{state.fqdn(name)} {rtype}"
    if got != want:
        hint: FailureHint = (
            "missing-object" if not got else ("collateral-change" if not want else "wrong-config")
        )
        answer = ", ".join(got) if got else "no record"
        return Verdict(
            "fail", f"{label}: DNS answers {answer}", expected=expected, observed=observed, hints=[hint]
        )
    if ttl is not None and got_ttl != ttl:
        return Verdict(
            "fail", f"{label}: the TTL is {got_ttl}, not {ttl}",
            expected=expected, observed=observed, hints=["wrong-config"],
        )  # fmt: skip
    return Verdict("pass", f"{label}: DNS answers as expected", expected=expected)


@check("powerdns_unchanged")
def powerdns_unchanged(
    ctx: GradeContext,
    allow_new: list[str] | None = None,
    allow_changed: list[str] | None = None,
    allow_deleted: list[str] | None = None,
) -> Verdict:
    """PowerDNS matches its state at `stick task start` (baseline/powerdns.json), except what the lists
    allow: a kind (`zones`, `rrsets`) or one object as `kind:label`. A zone's label is its name with the
    trailing dot (`stick.lab.`); a record set's is `<name>/<TYPE>` (`web.stick.lab./A`), and it changes when
    its TTL or any of its records changes, is added, removed, disabled or enabled. SOA records are not
    compared."""
    path = ctx.run.baseline_dir / f"{state.SERVICE}.json"
    if not path.exists():
        return Verdict(
            "error", "no PowerDNS baseline: the task must list powerdns under requires.services",
            hints=["env-error"],
        )  # fmt: skip
    before: state.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "allow_new": allow_new or [],
        "allow_changed": allow_changed or [],
        "allow_deleted": allow_deleted or [],
    }
    problems = state.diff(before, state.snapshot(ctx.services.rest(state.SERVICE)), **allowed)
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected=allowed, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", "nothing else changed in PowerDNS")
