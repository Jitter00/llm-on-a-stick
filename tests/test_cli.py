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
        cli.app, ["run", "running-config-cli-frr", "--model", "strata/a", "--model", "ollama/b"]
    )
    assert res.exit_code == 2
    assert "one after another" in res.output
