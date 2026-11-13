from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_on_a_stick import __version__, cli, doctor

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_task_lint_empty_dir(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["task", "lint", str(tmp_path)])
    assert result.exit_code == 0
    assert "0 task file(s) checked" in result.stdout


def test_doctor_json_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    h = doctor.HostInfo("linux", "amd64", 8, 32768, 30000, 100.0)
    d = doctor.DockerInfo(reachable=False, error="no socket")
    c = doctor.ContainerlabInfo(installed=True, version="0.82.0")
    b = doctor.compute_budget(h, d)
    caps, checks = doctor.evaluate(h, d, c, False, b)
    report = doctor.Report(h, d, c, False, [], [], b, caps, checks)
    monkeypatch.setattr(doctor, "run_doctor", lambda reserve_mb=0: report)

    result = runner.invoke(cli.app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["docker"]["error"] == "no socket"


def test_run_refuses_two_local_models() -> None:
    res = runner.invoke(
        cli.app, ["run", "config-interface-frr", "--model", "strata/a", "--model", "ollama/b"]
    )
    assert res.exit_code == 2
    assert "one after another" in res.output


def test_report_html_without_runs(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["report", str(tmp_path), "--html"])
    assert result.exit_code == 1
    assert not (tmp_path / "report.html").exists()


def test_vs_needs_two_different_models() -> None:
    assert runner.invoke(cli.app, ["vs", "ollama/a"]).exit_code == 2
    result = runner.invoke(cli.app, ["vs", "ollama/a", "ollama/a", "--all"])
    assert result.exit_code == 2


def test_vs_refuses_two_local_models(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["vs", "ollama/a", "strata/b", "--all", "--runs-dir", str(tmp_path / "vs")]
    )
    assert result.exit_code == 2
    assert not (tmp_path / "vs").exists()


def test_run_explains_a_task_id_given_as_a_section() -> None:
    result = runner.invoke(cli.app, ["run", "--model", "ollama/x", "--section", "bgp-peering-audit"])
    assert result.exit_code == 2
    assert "is a task, not a section" in result.output.replace("\n", " ")


def test_run_lists_the_sections_for_an_unknown_one() -> None:
    result = runner.invoke(cli.app, ["run", "--model", "ollama/x", "--section", "nope"])
    assert result.exit_code == 2
    assert "cfg-mgmt" in result.output
