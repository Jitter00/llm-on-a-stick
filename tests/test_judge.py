"""The judge model: grading/judge.py, the split in grading/grade.py, and the commands that use it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from llm_on_a_stick import cli, tasks
from llm_on_a_stick.grading import judge
from llm_on_a_stick.grading.results import Result
from llm_on_a_stick.runner import loop, models, report
from llm_on_a_stick.runner.models import ToolCall, Turn, Usage
from llm_on_a_stick.tasks import CheckSpec
from test_runner import ListClient, _call, demo  # noqa: F401 (demo is a fixture)

runner = CliRunner()
RUBRIC = "5: read the device before writing. 1: guessed. Canary: {{ canaries.host_desc }}"


class FakeJudge:
    """A judge that plays back answers: a dict is a tool call's arguments, a str is reply text, an
    exception is raised."""

    def __init__(self, answers: list[Any], spec: str = "anthropic/claude-haiku-5-5") -> None:
        self.spec = models.parse_spec(spec)
        self.sampling: dict[str, Any] = {"thinking": "disabled"}
        self.sampling_source = "default"
        self.context_window = None
        self.answers = answers
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def check(self) -> None:
        pass

    def new_session(self, system: str, prompt: str, tools: Any, variables: dict[str, Any]) -> Any:
        self.systems.append(system)
        self.prompts.append(prompt)
        outer, name = self, tools[0].name

        class S:
            def step(self) -> Turn:
                answer = outer.answers.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                if isinstance(answer, str):
                    return Turn(answer, [], Usage(100, 10), "end_turn")
                return Turn("", [ToolCall("j1", name, answer)], Usage(100, 10), "tool_use")

        return S()


def verdict(score: Any, reason: str = "it read the device first") -> dict[str, Any]:
    return {"score": score, "reason": reason}


@pytest.fixture
def attempt(demo: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    """A failed attempt by ollama/gemma4:12b at the demo task, which has one judge check."""
    task, lab = demo
    task.checks.append(CheckSpec(type="llm_judge", name="method", params={"rubric": RUBRIC}))
    monkeypatch.setattr(judge, "load_task", lambda _: task)
    turns = [
        Turn("looking", [_call("show running-config")], Usage(10, 1), "tool_use"),
        Turn("I am done", [], Usage(20, 2), "end_turn"),
    ]
    info, result, _ = loop.run_task(task, ListClient(turns, "ollama/gemma4:12b"), lab, tmp_path / "runs")
    assert result.outcome != "pass"
    return info.run_dir


def saved(run_dir: Path) -> Result:
    return Result.model_validate_json((run_dir / "result.json").read_text())


# --------------------------------------------------------------------------- grading keeps them apart


def test_grade_leaves_judge_checks_ungraded_and_out_of_the_score(attempt: Path) -> None:
    r = saved(attempt)
    assert "llm_judge" not in [c.type for c in r.checks]  # code checks only
    assert r.judge is not None and r.judge.model is None and r.judge.score is None
    (check,) = r.judge.checks
    assert (check.name, check.status, check.artifact, check.scale) == (
        "method",
        "not-graded",
        "transcript",
        5,
    )
    assert "--judge-model" in check.reason


def test_a_task_without_judge_checks_has_no_judge_section(demo: Any, tmp_path: Path) -> None:  # noqa: F811
    task, lab = demo
    _, result, _ = loop.run_task(
        task, ListClient([Turn("no", [], Usage(1, 1), "end")], "ollama/a"), lab, tmp_path
    )
    assert result.judge is None


# --------------------------------------------------------------------------- judging


def test_judge_fills_in_its_own_section_and_nothing_else(attempt: Path) -> None:
    before = saved(attempt)
    client = FakeJudge(
        [verdict(4), verdict(4), verdict(2, "it guessed"), {"summary": "It never saved the file."}]
    )
    result, asked = judge.judge_run(attempt, client)  # type: ignore[arg-type]
    assert asked and result == saved(attempt)

    after = saved(attempt)
    assert (after.outcome, after.score, after.checks, after.failure_hints, after.metrics) == (
        before.outcome, before.score, before.checks, before.failure_hints, before.metrics,
    )  # fmt: skip
    j = after.judge
    assert j is not None and (j.model, j.repeats, j.sampling) == (
        "anthropic/claude-haiku-5-5",
        3,
        client.sampling,
    )
    (check,) = j.checks
    assert (check.status, check.score, check.scores, check.agreement) == ("graded", 4, [4, 4, 2], 0.67)
    assert check.reason == "it read the device first"  # of a repeat that gave the median
    assert j.score == 0.75 and j.summary == "It never saved the file."
    assert (j.tokens_in, j.tokens_out) == (400, 40) and j.cost_usd == pytest.approx(0.00006)
    assert j.judged_at is not None


def test_the_judge_is_not_told_who_made_the_attempt(attempt: Path) -> None:
    client = FakeJudge([verdict(3)] * 3 + [{"summary": "s"}])
    judge.judge_run(attempt, client)  # type: ignore[arg-type]
    text = "\n".join(client.prompts + client.systems)
    assert "gemma" not in text and "ollama" not in text
    info = json.loads((attempt / "run.json").read_text())
    assert f"Canary: {info['canaries']['host_desc']}" in client.prompts[0]  # the rubric is rendered
    assert "$ show running-config" in client.prompts[0] and "[said] I am done" in client.prompts[0]
    assert "no-tool-use" not in client.prompts[0]  # a verdict doesn't see what the grader found...
    assert "failed check:" in client.prompts[3]  # ...the failure summary does


def test_a_passed_attempt_gets_no_summary(attempt: Path) -> None:
    r = saved(attempt)
    r.outcome, r.score = "pass", 1.0
    (attempt / "result.json").write_text(r.model_dump_json())
    client = FakeJudge([verdict(5)] * 3)
    result, _ = judge.judge_run(attempt, client)  # type: ignore[arg-type]
    assert result.judge is not None and result.judge.summary == "" and client.answers == []
    assert (result.outcome, result.judge.score) == ("pass", 1.0)


@pytest.mark.parametrize(
    ("answers", "status", "score"),
    [
        (['here: {"score": 2, "reason": "json in the reply"}'] * 3, "graded", 2),
        ([verdict(9), verdict("high"), verdict(True)], "error", None),  # nothing from 1 to 5
        ([verdict(9), verdict(3), "no idea"], "graded", 3),  # unusable repeats are dropped
        ([models.ModelError("503")] * 3, "error", None),
    ],
)
def test_verdicts_that_are_not_tool_calls(attempt: Path, answers: list[Any], status: str, score: Any) -> None:
    before = saved(attempt)
    result, _ = judge.judge_run(attempt, FakeJudge([*answers, {"summary": ""}]))  # type: ignore[arg-type]
    assert result.judge is not None
    (check,) = result.judge.checks
    assert (check.status, check.score) == (status, score)
    assert result.judge.score == (None if score is None else (score - 1) / 4)
    assert (result.outcome, result.score) == (before.outcome, before.score)


def test_a_model_never_judges_itself(attempt: Path) -> None:
    for spec in ("ollama/gemma4:12b", "strata/gemma4:12b", "openrouter/google/Gemma4:12b"):
        with pytest.raises(judge.JudgeError, match="can't judge its own attempts"):
            judge.judge_run(attempt, FakeJudge([], spec))  # type: ignore[arg-type]
    assert saved(attempt).judge.model is None  # type: ignore[union-attr]
    assert not judge.same_model("ollama/gemma4:26b", "ollama/gemma4:12b")
    assert not judge.same_model("ollama/x", "")  # an attempt made by hand: no model to compare with


def test_judged_once_unless_forced(attempt: Path) -> None:
    judge.judge_run(attempt, FakeJudge([verdict(2)] * 3 + [{"summary": "s"}]))  # type: ignore[arg-type]
    again = FakeJudge([verdict(5)] * 3 + [{"summary": "s"}])
    result, asked = judge.judge_run(attempt, again)  # type: ignore[arg-type]
    assert not asked and len(again.answers) == 4 and result.judge.checks[0].score == 2  # type: ignore[union-attr]
    result, asked = judge.judge_run(attempt, again, force=True)  # type: ignore[arg-type]
    assert asked and result.judge.checks[0].score == 5  # type: ignore[union-attr]
    other = FakeJudge([verdict(1)] * 3 + [{"summary": "s"}], "anthropic/claude-sonnet-5-5")
    assert judge.judge_run(attempt, other)[1]  # type: ignore[arg-type]  # another judge: judged again


def test_missing_artifacts_and_ungraded_runs(attempt: Path, tmp_path: Path) -> None:
    (attempt / "transcript.jsonl").unlink()  # as after `stick task start` + another agent + `stick grade`
    result, _ = judge.judge_run(attempt, FakeJudge([]))  # type: ignore[arg-type]
    (check,) = result.judge.checks  # type: ignore[union-attr]
    assert check.status == "not-graded" and "no transcript" in check.reason
    assert result.judge.summary == "" and result.judge.score is None  # type: ignore[union-attr]
    (tmp_path / "empty").mkdir()
    with pytest.raises(judge.JudgeError, match="grade it first"):
        judge.judge_run(tmp_path / "empty", FakeJudge([]))  # type: ignore[arg-type]


def test_reply_and_file_artifacts(attempt: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = judge.load_task(attempt)
    task.checks[-1].params["artifact"] = "reply"
    task.checks.append(
        CheckSpec(type="llm_judge", name="notes", params={"rubric": RUBRIC, "artifact": "notes.md"})
    )
    task.checks.append(
        CheckSpec(type="llm_judge", name="out", params={"rubric": RUBRIC, "artifact": "../run.json"})
    )
    client = FakeJudge([verdict(3)] * 3 + [{"summary": "s"}])
    result, _ = judge.judge_run(attempt, client)  # type: ignore[arg-type]
    reply, notes, outside = result.judge.checks  # type: ignore[union-attr]
    assert reply.status == "graded" and '<attempt kind="reply">\nI am done\n</attempt>' in client.prompts[0]
    assert (notes.status, notes.reason) == ("not-graded", "notes.md was not written")
    assert outside.status == "error" and "escapes the workspace" in outside.reason


def test_long_transcripts_lose_their_middle(tmp_path: Path) -> None:
    events = [{"kind": "start", "model": "ollama/secret-model", "prompt": "p"}]
    for n in range(1, 41):
        events.append({"kind": "turn", "n": n, "text": f"step {n}", "tool_calls": [{}]})
        events.append({"kind": "command", "command": f"cmd{n}", "exit_code": 0, "output": "x" * 5000})
    events.append({"kind": "end", "stop_reason": "max_turns", "outcome": "fail", "score": 0.0})
    (tmp_path / "transcript.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    full = judge.render_transcript(tmp_path)
    assert "secret-model" not in full and '"fail"' not in full and "the attempt ended: max_turns" in full
    assert full.count("characters omitted") == 40  # each long output is shortened
    short = judge.render_transcript(tmp_path, max_chars=20_000)
    assert len(short) <= 20_000 + 100 and "turn(s) left out" in short
    assert "--- turn 1 ---" in short and "--- turn 40 ---" in short and "--- turn 20 ---" not in short
    assert judge.render_transcript(tmp_path / "nowhere") == ""


# --------------------------------------------------------------------------- task files


def test_lint_rules_for_judge_checks(tmp_path: Path) -> None:
    def problems(checks: str) -> list[str]:
        folder = tmp_path / "t1"
        folder.mkdir(exist_ok=True)
        (folder / "task.yaml").write_text(
            "id: t1\nsection: netbox\ntitle: A task\ntier: basic\nprompt: do the thing now\nchecks:\n"
            + checks
        )
        return [e.message for e in tasks.lint_file(folder / "task.yaml")]

    code = "  - {type: file_exists, params: {path: a}}\n"
    good = "  - {type: llm_judge, params: {rubric: '5 is careful work, 1 is guessing'}}\n"
    assert problems(code + good) == []
    assert "needs a code check too" in problems(good)[0]
    assert "needs a `rubric`" in problems(code + "  - {type: llm_judge}\n")[0]
    rubric = "rubric: '5 is careful work, 1 is guessing'"
    bad = f"  - {{type: llm_judge, params: {{{rubric}, artifact: ../x, scale: 1, who: me}}}}\n"
    assert len(problems(code + bad)) == 3


def test_the_netbox_tasks_have_a_judge_check() -> None:
    from llm_on_a_stick import paths

    found = [tasks.load_task(p) for p in tasks.discover([paths.sections_dir() / "netbox"])]
    assert len(found) == 5
    for task in found:
        assert [c.params["artifact"] for c in task.checks if c.type == tasks.JUDGE_CHECK] == ["transcript"], (
            task.id
        )


# --------------------------------------------------------------------------- reports


def test_reports_show_the_judge_apart_from_the_score(attempt: Path) -> None:
    judge.judge_run(attempt, FakeJudge([verdict(4)] * 3 + [{"summary": "It never saved."}]))  # type: ignore[arg-type]
    rows = report.collect([attempt])
    (summary,) = report.summarise(rows)
    assert (rows[0].judge_score, summary.judge_score) == (0.75, 0.75)
    assert summary.mean_score == pytest.approx(rows[0].score, abs=0.001)  # the judge's 0.75 is not in it
    assert "| 0.75 |" in report.to_markdown(rows)
    data = report.build_report(report.collect_attempts([attempt]))
    assert data["judges"] == ["anthropic/claude-haiku-5-5"]
    c = data["contenders"][0]
    assert (c["judge_score"], c["judge_attempts"]) == (0.75, 1)
    assert c["mean_score"] == pytest.approx(rows[0].score, abs=0.001)
    assert next(iter(data["attempts"].values()))["judge"]["summary"] == "It never saved."


# --------------------------------------------------------------------------- commands


def test_run_and_vs_refuse_a_judge_that_is_a_tested_model() -> None:
    for args in (
        ["run", "netbox-drift", "--model", "ollama/a", "--judge-model", "strata/a"],
        ["vs", "ollama/a", "anthropic/b", "netbox-drift", "--judge-model", "openrouter/anthropic/b"],
    ):
        res = runner.invoke(cli.app, args)
        assert res.exit_code == 2 and "can't judge its own attempts" in res.output, res.output


def test_judge_command(attempt: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[FakeJudge] = []

    def make(spec: str, base_url: str | None = None) -> FakeJudge:
        made.append(FakeJudge([verdict(4), verdict(4), verdict(5), {"summary": "It never saved."}], spec))
        return made[-1]

    monkeypatch.setattr(judge, "make_judge", make)
    monkeypatch.setattr(tasks, "load_task", judge.load_task)  # the command counts the task's judge checks
    res = runner.invoke(cli.app, ["judge", str(attempt.parent), "--judge-model", "ollama/gemma4:12b"])
    assert res.exit_code == 2 and "can't judge its own attempts" in res.output and not made

    res = runner.invoke(
        cli.app, ["judge", str(attempt.parent), "--judge-model", "anthropic/claude-haiku-5-5"]
    )
    assert res.exit_code == 0, res.output
    assert (
        "1 attempt, asking the judge up to 4 times" in res.output
        and "method: 4/5, repeats gave 4/4/5" in res.output
    )
    assert "It never saved." in res.output and saved(attempt).judge.score == 0.75  # type: ignore[union-attr]

    res = runner.invoke(
        cli.app, ["judge", str(attempt.parent), "--judge-model", "anthropic/claude-haiku-5-5"]
    )
    assert res.exit_code == 0 and "already" in res.output and len(made) == 1
    assert (
        runner.invoke(cli.app, ["judge", str(attempt / "work"), "--judge-model", "ollama/x"]).exit_code == 2
    )
