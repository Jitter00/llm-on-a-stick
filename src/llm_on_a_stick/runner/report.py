"""`stick report`: compare model runs side by side (reads result.json from run folders)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from llm_on_a_stick.grading.results import Result


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


def collect(paths: list[Path]) -> list[Row]:
    """Model runs (with runner metrics) under the given run folders or folders of runs."""
    found: list[Path] = []
    for p in paths:
        if (p / "result.json").exists():
            found.append(p / "result.json")
        else:
            found.extend(sorted(p.glob("*/result.json")))
    rows = []
    for path in found:
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
            )
        )
    return out


def to_json(rows: list[Row]) -> str:
    return json.dumps(
        {"models": [asdict(s) for s in summarise(rows)], "runs": [asdict(r) for r in rows]}, indent=2
    )


def _cost(c: float | None) -> str:
    return "?" if c is None else f"${c:.4f}"


def to_markdown(rows: list[Row]) -> str:
    lines = [
        "| model | sampling | runs | passed | mean score | tokens | cost | mean time "
        "| most common problems |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summarise(rows):
        lines.append(
            f"| {s.model} | {s.sampling or '-'} | {s.runs} | {s.passed} | {s.mean_score:.2f} | {s.tokens} "
            f"| {_cost(s.cost_usd)} "
            f"| {s.mean_wall_s}s | {', '.join(s.common_hints) or '-'} |"
        )
    lines += [
        "",
        "| task | model | outcome | score | turns | tokens in/out | cost | time | problems |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.task_id} | {r.model} | {r.outcome} | {r.score:.2f} | {r.turns} "
            f"| {r.tokens_in}/{r.tokens_out} "
            f"| {_cost(r.cost_usd)} | {r.wall_s:.0f}s | {', '.join(r.hints) or '-'} |"
        )
    return "\n".join(lines) + "\n"
