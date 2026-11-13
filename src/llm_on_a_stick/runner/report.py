"""`stick report`: compare model runs side by side (reads result.json from run folders)."""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from llm_on_a_stick import __version__
from llm_on_a_stick.grading.results import HINT_TEXT, Result


@dataclass
class Row:
    model: str
    task_id: str
    run_dir: str
    outcome: str
    score: float
    hints: list[str]
    turns: int
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    wall_s: float
    stop_reason: str
    sampling: str = ""  # e.g. "temperature 1.0, top_p 0.95"
    judge_score: float | None = (
        None  # the judge model's score (0..1), when one judged it; not part of `score`
    )


def sampling_label(sampling: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sampling.items() if v is not None)


@dataclass
class ModelSummary:
    model: str
    sampling: str
    runs: int
    passed: int
    mean_score: float
    tokens: int
    cost_usd: float | None
    mean_wall_s: float
    common_hints: list[str] = field(default_factory=list)
    judge_score: float | None = None  # mean over the attempts a judge scored; never mixed into mean_score


def _result_files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        if (p / "result.json").exists():
            found.append(p / "result.json")
        else:
            found.extend(sorted(p.glob("*/result.json")))
    return found


def collect(paths: list[Path]) -> list[Row]:
    """Model runs (with runner metrics) under the given run folders or folders of runs."""
    rows = []
    for path in _result_files(paths):
        try:
            r = Result.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        mt: dict[str, Any] = r.metrics
        if not mt.get("model"):
            continue  # a run done by hand (`stick task start` + `stick grade`)
        rows.append(
            Row(
                model=mt["model"],
                task_id=r.task_id,
                run_dir=str(path.parent),
                outcome=r.outcome,
                score=r.score,
                hints=list(r.failure_hints),
                turns=int(mt.get("turns", 0)),
                tokens_in=int(mt.get("tokens_in", 0)),
                tokens_out=int(mt.get("tokens_out", 0)),
                cost_usd=mt.get("cost_usd"),
                wall_s=float(mt.get("wall_s", 0.0)),
                stop_reason=str(mt.get("stop_reason", "")),
                sampling=sampling_label(mt.get("sampling") or {}),
                judge_score=r.judge.score if r.judge else None,
            )
        )
    return sorted(rows, key=lambda r: (r.task_id, r.model, r.run_dir))


def summarise(rows: list[Row]) -> list[ModelSummary]:
    out = []
    # The same model at different sampling settings is summarised separately.
    for model, sampling in sorted({(r.model, r.sampling) for r in rows}):
        mine = [r for r in rows if (r.model, r.sampling) == (model, sampling)]
        costs = [r.cost_usd for r in mine]
        hint_counts: dict[str, int] = {}
        for r in mine:
            for h in r.hints:
                hint_counts[h] = hint_counts.get(h, 0) + 1
        top = sorted(hint_counts, key=lambda h: -hint_counts[h])[:4]
        out.append(
            ModelSummary(
                model=model,
                sampling=sampling,
                runs=len(mine),
                passed=sum(r.outcome == "pass" for r in mine),
                mean_score=round(mean(r.score for r in mine), 3),
                tokens=sum(r.tokens_in + r.tokens_out for r in mine),
                cost_usd=None if any(c is None for c in costs) else round(sum(c or 0 for c in costs), 4),
                mean_wall_s=round(mean(r.wall_s for r in mine), 1),
                common_hints=[f"{h} ({hint_counts[h]})" for h in top],
                judge_score=_mean_or_none([r.judge_score for r in mine]),
            )
        )
    return out


def _mean_or_none(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(mean(known), 3) if known else None


def _judge(score: float | None) -> str:
    return "-" if score is None else f"{score:.2f}"


def to_json(rows: list[Row]) -> str:
    return json.dumps(
        {"models": [asdict(s) for s in summarise(rows)], "runs": [asdict(r) for r in rows]}, indent=2
    )


def _cost(c: float | None) -> str:
    return "?" if c is None else f"${c:.4f}"


def to_markdown(rows: list[Row]) -> str:
    lines = [
        "| model | sampling | runs | passed | mean score | judge | tokens | cost | mean time "
        "| most common problems |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summarise(rows):
        lines.append(
            f"| {s.model} | {s.sampling or '-'} | {s.runs} | {s.passed} | {s.mean_score:.2f} "
            f"| {_judge(s.judge_score)} | {s.tokens} "
            f"| {_cost(s.cost_usd)} "
            f"| {s.mean_wall_s}s | {', '.join(s.common_hints) or '-'} |"
        )
    lines += [
        "",
        "| task | model | outcome | score | judge | turns | tokens in/out | cost | time | problems |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.task_id} | {r.model} | {r.outcome} | {r.score:.2f} | {_judge(r.judge_score)} | {r.turns} "
            f"| {r.tokens_in}/{r.tokens_out} "
            f"| {_cost(r.cost_usd)} | {r.wall_s:.0f}s | {', '.join(r.hints) or '-'} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- the full report

# Runner counters worth a line in "where it struggled", with the words for them.
COUNTERS = {
    "command_failures": "Commands that failed (non-zero exit code, or an MCP tool's error)",
    "command_timeouts": "Commands or MCP tool calls that timed out",
    "tool_errors": "Malformed tool calls",
    "commands_not_run": "Commands cut off before they could run",
    "output_limit_hits": "Replies that hit the output-token cap",
    "repetition_loops": "Replies that ended in a repetition loop",
    "empty_replies": "Empty replies",
}
STOP_TEXT = {
    "max_turns": "ran out of turns",
    "timeout": "hit the time limit",
    "token_limit": "hit the token limit",
    "model_error": "ended on a model server error",
    "refusal": "ended with a refusal",
    "low_memory": "stopped because the host ran low on memory",
    "output_limit": "ended on the output-token cap",
    "empty_reply": "ended on an empty reply",
    "context_full": "filled the context window",
}


@dataclass
class AttemptDetail:
    """One attempt with everything the report page shows."""

    id: str
    model: str
    sampling: str
    task_id: str
    section: str
    title: str
    tier: str
    run_dir: str
    started_at: str
    stick_version: str
    outcome: str
    score: float
    hints: list[str]
    checks: list[dict[str, Any]]
    metrics: dict[str, Any]
    prompt: str
    events: list[dict[str, Any]]
    judge: dict[str, Any] | None = None  # result.json's `judge`: the judge model's checks and summary
    repeat: int = 1  # 1-based, by start time within (model, sampling, task)
    contender: str = ""  # set by build_report


def _task_meta(task_dir: str, task_id: str, cache: dict[str, tuple[str, str, str]]) -> tuple[str, str, str]:
    """(section, title, tier). The task may have been removed since the run: fall back to the folder name."""
    if task_dir not in cache:
        section, title, tier = (Path(task_dir).parent.name if task_dir else ""), task_id, ""
        try:
            data = yaml.safe_load((Path(task_dir) / "task.yaml").read_text(encoding="utf-8"))
            if isinstance(data, dict) and task_dir:
                section = str(data.get("section") or section)
                title = str(data.get("title") or title)
                tier = str(data.get("tier") or "")
        except (OSError, yaml.YAMLError):
            pass
        cache[task_dir] = (section, title, tier)
    return cache[task_dir]


def _events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        for call in e.get("tool_calls") or []:
            if isinstance(call, dict):
                call.pop("raw_arguments", None)  # the parsed arguments are enough
        events.append(e)
    return events


def collect_attempts(paths: list[Path]) -> list[AttemptDetail]:
    """Like `collect`, with the checks, metrics, prompt and transcript of every attempt."""
    out: list[AttemptDetail] = []
    meta: dict[str, tuple[str, str, str]] = {}
    for path in _result_files(paths):
        try:
            r = Result.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not r.metrics.get("model"):
            continue
        run: dict[str, Any] = {}
        with contextlib.suppress(OSError, ValueError):
            run = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
        section, title, tier = _task_meta(str(run.get("task_dir") or ""), r.task_id, meta)
        out.append(
            AttemptDetail(
                id=r.run_id,
                model=str(r.metrics["model"]),
                sampling=sampling_label(r.metrics.get("sampling") or {}),
                task_id=r.task_id,
                section=section,
                title=title,
                tier=tier,
                run_dir=str(path.parent),
                started_at=r.started_at.isoformat(),
                stick_version=r.stick_version,
                outcome=r.outcome,
                score=r.score,
                hints=list(r.failure_hints),
                checks=[c.model_dump() for c in r.checks],
                metrics=r.metrics,
                prompt=str(run.get("prompt") or ""),
                events=_events(path.parent / "transcript.jsonl"),
                judge=r.judge.model_dump(mode="json") if r.judge else None,
            )
        )
    out.sort(key=lambda a: (a.task_id, a.model, a.sampling, a.started_at))
    seen: Counter[tuple[str, str, str]] = Counter()
    for a in out:
        seen[(a.task_id, a.model, a.sampling)] += 1
        a.repeat = seen[(a.task_id, a.model, a.sampling)]
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _struggles(mine: list[AttemptDetail]) -> dict[str, Any]:
    """Where one contender had trouble. Rules over the recorded results: no judge model."""
    n = len(mine)
    by_task: dict[str, list[AttemptDetail]] = {}
    for a in mine:
        by_task.setdefault(a.task_id, []).append(a)
    never = [t for t, xs in by_task.items() if not any(a.outcome == "pass" for a in xs)]
    sometimes = [t for t, xs in by_task.items() if t not in never and any(a.outcome != "pass" for a in xs)]

    hint_counts = Counter(h for a in mine for h in a.hints)
    hints = [{"hint": h, "count": c, "text": HINT_TEXT.get(h, "")} for h, c in hint_counts.most_common()]

    checks: dict[tuple[str, str], dict[str, Any]] = {}
    for a in mine:
        for c in a.checks:
            entry = checks.setdefault(
                (a.task_id, c["name"]),
                {"task_id": a.task_id, "name": c["name"], "failed": 0, "total": 0, "messages": Counter()},
            )
            entry["total"] += 1
            if c["status"] != "pass":
                entry["failed"] += 1
                entry["messages"][c["message"]] += 1
                entry.setdefault("example", {"attempt": a.id, **{k: c[k] for k in ("expected", "observed")}})
    failed_checks = []
    for entry in sorted(checks.values(), key=lambda e: (-e["failed"], e["task_id"], e["name"])):
        if entry["failed"]:
            messages: Counter[str] = entry.pop("messages")
            failed_checks.append({**entry, "message": messages.most_common(1)[0][0]})

    stops = Counter(str(a.metrics.get("stop_reason") or "") for a in mine)
    stops.pop("done", None)
    stops.pop("", None)
    counters = {k: sum(int(a.metrics.get(k) or 0) for a in mine) for k in COUNTERS}
    commands = sum(int(a.metrics.get("tool_calls") or 0) for a in mine)

    passed = sum(a.outcome == "pass" for a in mine)
    summary = []
    if passed == n:
        summary.append(f"Passed all {_plural(n, 'attempt')}.")
    else:
        summary.append(f"Passed {passed} of {_plural(n, 'attempt')}.")
    if never:
        summary.append(f"Never passed: {', '.join(sorted(never))}.")
    if sometimes:
        parts = [
            f"{t} ({sum(a.outcome == 'pass' for a in by_task[t])} of {len(by_task[t])})"
            for t in sorted(sometimes)
        ]
        summary.append(f"Passed only sometimes: {', '.join(parts)}.")
    for reason, count in stops.most_common():
        summary.append(f"{_plural(count, 'attempt')} {STOP_TEXT.get(reason, 'stopped: ' + reason)}.")
    if hints:
        top = hints[0]
        why = f": {top['text']}" if top["text"] else ""
        count = hint_counts[str(top["hint"])]
        summary.append(f"Most common problem: {top['hint']} ({_plural(count, 'attempt')}){why}.")
    if failed_checks:
        worst = failed_checks[0]
        summary.append(
            f'Check that failed most: "{worst["name"]}" in {worst["task_id"]} '
            f"({worst['failed']} of {worst['total']}): {worst['message']}."
        )
    for key, words in COUNTERS.items():
        if counters[key]:
            of = f" of {commands}" if key.startswith("command_") and commands else ""
            summary.append(f"{words}: {counters[key]}{of}.")

    return {
        "summary": summary,
        "never_passed": sorted(never),
        "sometimes_passed": sorted(sometimes),
        "hints": hints,
        "failed_checks": failed_checks,
        "stop_reasons": dict(stops),
        "counters": counters,
    }


def _stats(mine: list[AttemptDetail]) -> dict[str, Any]:
    costs: list[float | None] = [a.metrics.get("cost_usd") for a in mine]
    scores: list[float | None] = [(a.judge or {}).get("score") for a in mine]
    return {
        "attempts": len(mine),
        "passed": sum(a.outcome == "pass" for a in mine),
        "mean_score": round(mean(a.score for a in mine), 3),
        "tokens_in": sum(int(a.metrics.get("tokens_in") or 0) for a in mine),
        "tokens_out": sum(int(a.metrics.get("tokens_out") or 0) for a in mine),
        "cost_usd": None if any(c is None for c in costs) else round(sum(c or 0.0 for c in costs), 4),
        "mean_wall_s": round(mean(float(a.metrics.get("wall_s") or 0) for a in mine), 1),
        "total_wall_s": round(sum(float(a.metrics.get("wall_s") or 0) for a in mine), 1),
        "mean_turns": round(mean(int(a.metrics.get("turns") or 0) for a in mine), 1),
        # The judge model's view, apart from the code score: mean over the attempts it scored.
        "judge_score": _mean_or_none(scores),
        "judge_attempts": sum(s is not None for s in scores),
        "judge_cost_usd": round(sum(float((a.judge or {}).get("cost_usd") or 0) for a in mine), 4),
    }


MAX_VERSUS = 3  # the head-to-head comparison is made for two or three contenders


def _versus(contenders: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Head to head for two or three contenders, over the tasks all of them attempted."""
    ids = [c["id"] for c in contenders]
    wins: dict[str, list[str]] = {**{i: [] for i in ids}, "tie": []}
    top: dict[str, list[str]] = {i: [] for i in ids}
    only: dict[str, list[str]] = {i: [] for i in ids}
    for t in tasks:
        per = t["per"]
        if not all(i in per for i in ids):
            continue
        wins[t["better"] or "tie"].append(t["id"])
        for i in t["leaders"]:
            top[i].append(t["id"])
        passed = [i for i in ids if per[i]["passed"]]
        if len(passed) == 1:
            only[passed[0]].append(t["id"])
    counts = {i: len(wins[i]) for i in ids}
    tied = len(wins["tie"])
    shared = sum(counts.values()) + tied
    if not shared:
        headline = f"The {'two' if len(ids) == 2 else 'models'} attempted no task in common."
    elif len(ids) > 2:
        # With three, two often share the lead, so "did better" alone says little: count best or joint best.
        order = sorted(contenders, key=lambda c: len(top[c["id"]]), reverse=True)  # stable: ties keep order
        headline = (
            f"Best or joint best on the {_plural(shared, 'task')} all attempted: "
            + ", ".join(f"{c['label']} on {len(top[c['id']])}" for c in order)
            + "."
        )
    elif len(set(counts.values())) == 1:
        headline = f"Level: each did better on {_plural(counts[ids[0]], 'task')}, {tied} tied."
    else:
        first, second = sorted(contenders, key=lambda c: counts[c["id"]], reverse=True)
        headline = (
            f"{first['label']} did better on {counts[first['id']]} of {_plural(shared, 'task')}, "
            f"{second['label']} on {counts[second['id']]}, {tied} tied."
        )
    return {"contenders": ids, "wins": wins, "top": top, "only_passed_by": only, "headline": headline}


def _rank(per: dict[str, Any]) -> tuple[float, float]:
    """A contender's standing on one task: pass rate first, then mean score."""
    return per["passed"] / len(per["attempts"]), per["mean_score"]


TIERS = ["basic", "intermediate", "advanced"]


def _breakdown(attempts: list[AttemptDetail], field_name: str, order: list[str]) -> list[dict[str, Any]]:
    """Passes and mean score per contender for each value of `field_name` ("section" or "tier"): values in
    `order` first, then the rest by name. Attempts without a value (a removed task) are left out."""
    groups: dict[str, dict[str, list[AttemptDetail]]] = {}
    for a in attempts:
        name = str(getattr(a, field_name))
        if name:
            groups.setdefault(name, {}).setdefault(a.contender, []).append(a)
    names = [n for n in order if n in groups] + sorted(n for n in groups if n not in order)
    return [
        {
            "name": name,
            "per": {
                cid: {
                    "tasks": len({a.task_id for a in theirs}),
                    "attempts": len(theirs),
                    "passed": sum(a.outcome == "pass" for a in theirs),
                    "mean_score": round(mean(a.score for a in theirs), 3),
                }
                for cid, theirs in groups[name].items()
            },
        }
        for name in names
    ]


def build_report(attempts: list[AttemptDetail], title: str = "") -> dict[str, Any]:
    """Everything the report page shows, as one JSON-ready structure (also written as report.json)."""
    keys = sorted({(a.model, a.sampling) for a in attempts})
    several = Counter(model for model, _ in keys)
    contenders: list[dict[str, Any]] = []
    for i, (model, sampling) in enumerate(keys):
        mine = [a for a in attempts if (a.model, a.sampling) == (model, sampling)]
        cid = f"c{i}"
        for a in mine:
            a.contender = cid
        label = f"{model} ({sampling})" if several[model] > 1 and sampling else model
        m = mine[-1].metrics
        contenders.append(
            {
                "id": cid,
                "label": label,
                "model": model,
                "sampling": sampling,
                "sampling_source": str(m.get("sampling_source") or ""),
                "provider": str(m.get("provider") or ""),
                "base_url": str(m.get("base_url") or ""),
                **_stats(mine),
                "struggles": _struggles(mine),
            }
        )

    tasks: list[dict[str, Any]] = []
    for task_id in sorted({a.task_id for a in attempts}):
        mine = [a for a in attempts if a.task_id == task_id]
        per: dict[str, dict[str, Any]] = {}
        for c in contenders:
            theirs = [a for a in mine if a.contender == c["id"]]
            if theirs:
                per[c["id"]] = {
                    "attempts": [a.id for a in theirs],
                    "passed": sum(a.outcome == "pass" for a in theirs),
                    "mean_score": round(mean(a.score for a in theirs), 3),
                }
        best = max((_rank(p) for p in per.values()), default=None)
        leaders = [c for c in per if _rank(per[c]) == best]  # more than one: they share the lead
        better = leaders[0] if len(per) > 1 and len(leaders) == 1 else None
        tasks.append(
            {
                "id": task_id,
                "section": mine[0].section,
                "title": mine[0].title,
                "tier": mine[0].tier,
                "per": per,
                "better": better,
                "leaders": leaders,
            }
        )
    tasks.sort(key=lambda t: (t["section"], t["id"]))

    started = sorted(a.started_at for a in attempts)
    return {
        "title": title,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generated_by": f"stick {__version__}",
        "first_attempt": started[0] if started else None,
        "last_attempt": started[-1] if started else None,
        # time spent in the attempts themselves; first to last attempt also spans the pauses between them
        "total_wall_s": round(sum(float(a.metrics.get("wall_s") or 0) for a in attempts), 1),
        "sections": sorted({a.section for a in attempts if a.section}),
        "stick_versions": sorted({a.stick_version for a in attempts}),
        "turn_limits": sorted(
            {int(n) for a in attempts if (n := (a.metrics.get("limits") or {}).get("turns"))}
        ),
        "contenders": contenders,
        # The judge models that scored these attempts (normally one). Their scores are never in `mean_score`.
        "judges": sorted({str(a.judge["model"]) for a in attempts if a.judge and a.judge.get("model")}),
        "tasks": tasks,
        # Totals per section and per tier. With one attempt per task and three tasks in a section, a section
        # moves in thirds: `max_repeats` lets the page say so.
        "by_section": _breakdown(attempts, "section", []),
        "by_tier": _breakdown(attempts, "tier", TIERS),
        "max_repeats": max((a.repeat for a in attempts), default=0),
        "versus": _versus(contenders, tasks) if 2 <= len(contenders) <= MAX_VERSUS else None,
        "attempts": {a.id: asdict(a) for a in attempts},
        "hint_text": HINT_TEXT,
    }
