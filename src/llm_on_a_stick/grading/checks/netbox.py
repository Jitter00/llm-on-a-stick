"""Source-of-truth checks beyond `netbox_object`: nothing else in NetBox (or Nautobot) changed."""

from __future__ import annotations

import json

from llm_on_a_stick.grading import sotstate
from llm_on_a_stick.grading.checks import Verdict, check
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.services.seed import RestError

SAMPLE = 10
_TITLES = {"netbox": "NetBox", "nautobot": "Nautobot"}


def unchanged(ctx: GradeContext, service: str, allow_new: list[str] | None) -> Verdict:
    """`service` matches its state at `stick task start` (baseline/<service>.json)."""
    title = _TITLES.get(service, service)
    path = ctx.run.baseline_dir / f"{service}.json"
    if not path.exists():
        return Verdict(
            "error", f"no {title} baseline: the task must list {service} under requires.services",
            hints=["env-error"],
        )  # fmt: skip
    before: sotstate.Snapshot = json.loads(path.read_text(encoding="utf-8"))
    after = sotstate.snapshot(ctx.services.rest(service), tuple(before))
    problems = sotstate.diff(before, after, allow_new or [])
    if problems:
        return Verdict(
            "fail", f"{len(problems)} change(s) the task didn't ask for",
            expected={"allow_new": allow_new or []}, observed=problems[:SAMPLE], hints=["collateral-change"],
        )  # fmt: skip
    return Verdict("pass", f"nothing else changed in {title}")


@check("netbox_unchanged")
def netbox_unchanged(ctx: GradeContext, allow_new: list[str] | None = None) -> Verdict:
    """NetBox matches its state at `stick task start` (baseline/netbox.json): nothing changed or deleted, and
    nothing added except on the `allow_new` endpoints (e.g. [dcim/devices, ipam/ip-addresses])."""
    return unchanged(ctx, "netbox", allow_new)


@check("nautobot_unchanged")
def nautobot_unchanged(ctx: GradeContext, allow_new: list[str] | None = None) -> Verdict:
    """Nautobot matches its state at `stick task start` (baseline/nautobot.json): nothing changed or
    deleted, and nothing added except on the `allow_new` endpoints (e.g. [ipam/ip-address-to-interface])."""
    return unchanged(ctx, "nautobot", allow_new)


@check("nautobot_graphql")
def nautobot_graphql(
    ctx: GradeContext,
    path: str,
    must_contain: list[str],
    must_not_contain: list[str] | None = None,
) -> Verdict:
    """The workspace file `path` holds a GraphQL query that Nautobot (/api/graphql/) answers without errors,
    and whose result holds every value in `must_contain` (e.g. device names, interface names, addresses) and
    none in `must_not_contain` (objects the query should have filtered out)."""
    file = ctx.workspace_file(path)
    query = file.read_text(encoding="utf-8", errors="replace").strip() if file.is_file() else ""
    if not query:
        return Verdict("fail", f"{path} is missing or empty", hints=["no-output"])
    try:
        reply = ctx.services.rest("nautobot").post("graphql/", {"query": query})
    except RestError as exc:
        if "HTTP 400" not in str(exc):
            raise
        return Verdict("fail", f"Nautobot rejected the query: {str(exc)[-300:]}", hints=["wrong-format"])
    if reply.get("errors"):
        errors = [e.get("message", str(e)) for e in reply["errors"]][:SAMPLE]
        return Verdict("fail", "the query returned errors", observed=errors, hints=["wrong-format"])
    values = set(_leaves(reply.get("data")))
    missing = [v for v in must_contain if v not in values]
    extra = [v for v in must_not_contain or [] if v in values]
    if missing or extra:
        return Verdict(
            "fail", f"the query's result lacks {len(missing)} expected value(s), has {len(extra)} unwanted",
            expected={"must_contain": must_contain, "must_not_contain": must_not_contain or []},
            observed={"missing": missing, "unwanted": extra},
            hints=["unfiltered-output" if extra and not missing else "missing-object"],
        )  # fmt: skip
    return Verdict("pass", f"the query returns all {len(must_contain)} expected value(s)")


def _leaves(value: object) -> list[str]:
    """Every scalar in a JSON value, as text."""
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in _leaves(v)]
    if isinstance(value, list):
        return [leaf for v in value for leaf in _leaves(v)]
    return [] if value is None else [str(value).strip()]
