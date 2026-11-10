"""What `stick run` starts by itself, and where containerlab keeps a lab's working files."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from llm_on_a_stick import cli
from llm_on_a_stick.env import containerlab


def _task(services: list[str] | None = None, devices: bool = True) -> Any:
    requires: dict[str, Any] = {"devices": ["srl1"]} if devices else {}
    if services:
        requires["services"] = services
    return SimpleNamespace(topology="base", requires=requires)


class _Fakes:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, lab_running: bool, healthy: set[str]) -> None:
        self.deployed: list[str] = []
        self.started: list[str] = []
        state = "running" if lab_running else "exited"
        nodes = [containerlab.LabNode("n", "linux", "x", state, "")] if lab_running else []
        monkeypatch.setattr(containerlab, "inspect", lambda topology: nodes)
        monkeypatch.setattr(containerlab, "deploy", lambda topology: self.deployed.append(topology))
        monkeypatch.setattr(cli, "_load_services", lambda names: [SimpleNamespace(name=n) for n in names])
        monkeypatch.setattr(cli.lifecycle, "healthy", lambda spec: spec.name in healthy)
        monkeypatch.setattr(cli.lifecycle, "up", lambda spec, log: self.started.append(spec.name))


def test_up_starts_only_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes = _Fakes(monkeypatch, lab_running=False, healthy={"netbox"})
    cli._bring_up([_task(["oxidized", "netbox"]), _task(["oxidized"]), _task()])
    assert fakes.deployed == ["base"]
    assert fakes.started == ["oxidized"]
    out = capsys.readouterr().out
    assert "to stop everything: stick env down" in out


def test_up_does_nothing_when_everything_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes = _Fakes(monkeypatch, lab_running=True, healthy={"oxidized"})
    cli._bring_up([_task(["oxidized"])])
    assert fakes.deployed == [] and fakes.started == []
    assert capsys.readouterr().out == ""


def test_up_leaves_the_lab_alone_for_tasks_without_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    fakes = _Fakes(monkeypatch, lab_running=False, healthy=set())
    cli._bring_up([_task(["moto"], devices=False)])
    assert fakes.deployed == []
    assert fakes.started == ["moto"]


def test_up_reports_a_failed_start(monkeypatch: pytest.MonkeyPatch) -> None:
    _Fakes(monkeypatch, lab_running=False, healthy=set())

    def fail(topology: str) -> None:
        raise containerlab.ContainerlabError("containerlab is not installed")

    monkeypatch.setattr(containerlab, "deploy", fail)
    with pytest.raises(typer.Exit) as exc:
        cli._bring_up([_task()])
    assert exc.value.exit_code == 2


class _Down:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, running: set[str], lab: bool) -> None:
        self.calls: list[str] = []
        monkeypatch.setattr(cli.services, "available", lambda: ["netbox", "oxidized"])
        monkeypatch.setattr(cli.services, "load", lambda name: SimpleNamespace(name=name))
        monkeypatch.setattr(cli.lifecycle, "status", lambda spec: [{}] if spec.name in running else [])
        monkeypatch.setattr(cli.lifecycle, "down", lambda spec: self.calls.append(spec.name))
        monkeypatch.setattr(containerlab, "inspect", lambda topology: [object()] if lab else [])
        monkeypatch.setattr(containerlab, "destroy", lambda topology: self.calls.append("lab"))


def test_env_down_stops_running_services_then_the_lab(monkeypatch: pytest.MonkeyPatch) -> None:
    down = _Down(monkeypatch, running={"oxidized"}, lab=True)
    result = CliRunner().invoke(cli.app, ["env", "down"])
    assert result.exit_code == 0
    assert down.calls == ["oxidized", "lab"]  # services first: they sit on the lab's network


def test_env_down_with_nothing_running(monkeypatch: pytest.MonkeyPatch) -> None:
    down = _Down(monkeypatch, running=set(), lab=False)
    result = CliRunner().invoke(cli.app, ["env", "down"])
    assert result.exit_code == 0 and down.calls == []


def test_report_name_says_what_was_run() -> None:
    one = cli._report_name(["anthropic/claude-haiku-5-5"], None, ["cfg-mgmt"], False)
    assert one.startswith("report-claude-haiku-5-5-cfg-mgmt-2") and one.endswith("Z.html")
    two = cli._report_name(["anthropic/claude-haiku-5-5", "ollama/gemma4:12b"], ["a-task"], None, False)
    assert two.startswith("report-claude-haiku-5-5-vs-gemma4-12b-a-task-")
    assert "-all-" in cli._report_name(["ollama/x"], None, None, True)
    assert "-2-tasks-" in cli._report_name(["ollama/x"], ["a", "b"], None, False)


def test_report_address_is_a_file_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    assert cli._file_url(tmp_path / "r.html") == (tmp_path / "r.html").resolve().as_uri()


def test_report_address_under_wsl_names_the_distribution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
    url = cli._file_url(tmp_path / "r.html")
    assert url.startswith("file://wsl.localhost/Ubuntu-24.04/")
    assert url.endswith(f"{tmp_path.resolve().as_posix()}/r.html")


def test_lab_files_go_outside_the_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("CLAB_LABDIR_BASE", raising=False)
    env = containerlab._env()
    assert env["CLAB_LABDIR_BASE"] == str(tmp_path / "stick" / "labs")
    assert (tmp_path / "stick" / "labs").is_dir()


def test_lab_files_setting_of_the_user_is_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAB_LABDIR_BASE", str(tmp_path / "mine"))
    assert containerlab._env()["CLAB_LABDIR_BASE"] == str(tmp_path / "mine")
    assert not (tmp_path / "mine").exists()
