"""`stick vs` in parallel: which instance each model gets, the local-model lock, the child processes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_on_a_stick import cli
from llm_on_a_stick.runner import schedule

LAB = 4000


def _plan(local: list[bool], *, busy: set[int] = frozenset(), usable: int = 100_000, **kw: object):  # type: ignore[no-untyped-def]
    return schedule.plan(local, kw.pop("here", 0), lambda n: n not in busy, lambda n: LAB, usable, **kw)  # type: ignore[arg-type]


def test_a_cloud_and_a_local_model_each_get_an_instance() -> None:
    plan = _plan([False, True])
    assert plan.parallel and plan.instances == (0, 1)
    assert _plan([False, False]).instances == (0, 1)  # two cloud models as well


def test_the_first_model_keeps_the_current_instance_and_the_second_takes_the_lowest_free() -> None:
    assert _plan([False, True], here=2).instances == (2, 0)
    assert _plan([False, True], busy={1}).instances == (0, 2)


def test_two_local_models_are_never_planned() -> None:
    with pytest.raises(schedule.ScheduleError, match="more than one local model"):
        _plan([True, True])
    with pytest.raises(schedule.ScheduleError):
        _plan([True, True], sequential=True)


def test_sequential_when_asked_or_when_it_does_not_fit() -> None:
    assert _plan([False, True], sequential=True).instances is None
    plan = _plan([False, True], busy={1, 2, 3})
    assert not plan.parallel and plan.reason == "no other lab instance is free"
    plan = _plan([False, True], usable=2 * LAB - 500)
    assert not plan.parallel and "500 MiB more RAM" in plan.reason
    assert _plan([False, True], usable=2 * LAB).parallel
    assert not _plan([False]).parallel


def test_what_is_running_already_costs_nothing() -> None:
    plan = schedule.plan([False, True], 0, lambda n: True, lambda n: 0 if n == 0 else LAB, LAB)
    assert plan.instances == (0, 1)


def test_local_model_lock_refuses_a_second_local_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fcntl")  # file locks: not on Windows, where there is no lab either
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert schedule.local_model_lock_path() == tmp_path / "stick" / "local-model.lock"
    with schedule.local_model_lock("ollama/a"):
        with (
            pytest.raises(schedule.ScheduleError, match="is testing ollama/a") as exc,
            schedule.local_model_lock("strata/b"),
        ):
            pass
        assert "strata/b" in str(exc.value)
    with schedule.local_model_lock("strata/b"):  # released
        pass


def test_children_run_at_the_same_time_with_labelled_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STICK_INSTANCE", "3")  # must not leak into the children
    code = "import os, sys; print(sys.argv[1], os.environ.get('STICK_INSTANCE')); sys.exit(int(sys.argv[2]))"
    lines: list[tuple[str, str]] = []
    codes = schedule.run_children(
        [
            ("a", [sys.executable, "-c", code, "first", "0"]),
            ("b", [sys.executable, "-c", code, "second", "1"]),
        ],
        lambda label, line: lines.append((label, line)),
    )
    assert codes == [0, 1]
    assert sorted(lines) == [("a", "first None"), ("b", "second None")]


def test_child_argv_names_the_instance() -> None:
    argv = schedule.child_argv(2, ["--model", "ollama/a", "--all"])
    assert argv[1:] == ["-m", "llm_on_a_stick", "--instance", "2", "run", "--model", "ollama/a", "--all"]


def test_run_options_rebuild_the_batch(tmp_path: Path) -> None:
    args = cli._run_options(
        ["bgp-peering-audit"], ["netbox"], False, 3, None, 12, None, 60, None, None, False, 2048, None,
        tmp_path, 7, "anthropic/claude-haiku-5-5", None, 2,
    )  # fmt: skip
    assert args == [
        "bgp-peering-audit", "--section", "netbox", "--repeat", "3", "--cmd-timeout", "60",
        "--min-free-ram", "2048", "--no-thinking", "--max-turns", "12", "--seed", "7",
        "--judge-model", "anthropic/claude-haiku-5-5", "--judge-repeats", "2",
        "--runs-dir", str(tmp_path), "--no-report",
    ]  # fmt: skip
    # `stick run` accepts every one of them: parsed only, nothing runs (no model server is asked).
    import typer

    run = typer.main.get_command(cli.app).commands["run"]  # type: ignore[attr-defined]
    params = run.make_context("run", ["--model", "ollama/x", *args, "--attempts-file", "x"]).params
    assert (params["repeat"], params["seed"], params["judge_repeats"]) == (3, 7, 2)
    assert params["section"] == ["netbox"] and params["no_report"] is True


FIXTURES = Path(__file__).parent / "fixtures"


def test_vs_starts_one_run_per_model_on_its_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = FIXTURES / "scripts" / "demo-frr-config-retrieval.yaml"
    second = tmp_path / "b.yaml"
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(cli, "_plan_instances", lambda *a, **k: schedule.Plan((0, 2), "a lab per model"))
    monkeypatch.setattr("llm_on_a_stick.runner.toolbox.ensure_image", lambda *a, **k: None)
    jobs: list[tuple[str, list[str]]] = []

    def fake(seen: list[tuple[str, list[str]]], log: object, columns: int | None = None) -> list[int]:
        jobs.extend(seen)
        log(seen[0][0], "hello from the first")  # type: ignore[operator]
        return [0, 1]

    monkeypatch.setattr(schedule, "run_children", fake)
    runs = tmp_path / "vs"
    result = CliRunner().invoke(
        cli.app,
        ["vs", f"script/{first}", f"script/{second}", "demo-frr-config-retrieval",
         "--tasks-dir", str(FIXTURES / "tasks"), "--runs-dir", str(runs)],
    )  # fmt: skip
    assert result.exit_code == 1, result.output  # the second child could not run an attempt
    assert "hello from the first" in result.output
    (_, a), (_, b) = jobs
    assert a[3:6] == ["--instance", "0", "run"] and b[3:6] == ["--instance", "2", "run"]
    assert b[6:8] == ["--model", f"script/{second}"]
    assert "--no-report" in b and "demo-frr-config-retrieval" in b
    assert b[b.index("--runs-dir") + 1] == str(runs)
    assert a[a.index("--attempts-file") + 1] != b[b.index("--attempts-file") + 1]


def test_vs_sequential_never_plans_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.doctor, "probe_host", lambda: pytest.fail("measured the machine"))
    assert not cli._plan_instances([False, True], [], sequential=True).parallel


def test_a_started_lab_is_waited_for_until_bgp_is_up(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_on_a_stick.grading.labstate import LabStateError, Node

    calls = {"srl1": 0, "frr1": 0}

    class Fake:
        def __init__(self, topology: str) -> None:
            pass

        def nodes(self) -> dict[str, Node]:
            return {n: Node(n, os, "", n) for n, os in (("srl1", "srlinux"), ("frr1", "frr"), ("h1", "host"))}  # type: ignore[arg-type]

        def bgp_sessions(self, node: str) -> dict[str, str]:
            calls[node] += 1
            if node == "srl1" and calls[node] == 1:
                raise LabStateError("not answering yet")
            if node == "frr1" and calls[node] < 3:
                return {"10.0.1.0": "active"}
            return {"10.0.1.0": "established"}

    monkeypatch.setattr(cli, "DockerLabState", Fake)
    cli._wait_converged("base", timeout_s=5, step_s=0)
    assert calls == {"srl1": 2, "frr1": 3}  # each asked until it was up, and not again; the host never
