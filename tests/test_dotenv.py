from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_on_a_stick import cli, dotenv
from llm_on_a_stick.runner import models

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
runner = CliRunner()


def test_parse() -> None:
    text = """
    # a comment
    PLAIN=http://127.0.0.1:8787/anthropic
    export EXPORTED = value
    QUOTED="two words # kept"
    SINGLE='x'
    TRAILING=600   # seconds
    EMPTY=
    not a setting
    1BAD=x
    """
    assert dotenv.parse(text) == {
        "PLAIN": "http://127.0.0.1:8787/anthropic",
        "EXPORTED": "value",
        "QUOTED": "two words # kept",
        "SINGLE": "x",
        "TRAILING": "600",
        "EMPTY": "",
    }


def test_load_keeps_what_the_environment_has(tmp_path: Path) -> None:
    file = tmp_path / "settings"
    file.write_text("A=file\nB=file\n")
    env = {"A": "shell"}
    assert dotenv.load(file, env) == ["B"]
    assert env == {"A": "shell", "B": "file"}


def test_load_missing_file(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    assert dotenv.load(tmp_path / "absent", env) == []
    assert env == {}


def test_cli_reads_the_file_and_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file = tmp_path / "settings"
    file.write_text("STICK_TEST_ONLY_SETTING=1\n")
    monkeypatch.setattr(cli, "ENV_FILE", str(file))
    monkeypatch.setattr(dotenv.os, "environ", dict(os.environ))  # don't leak into other tests
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert dotenv.os.environ["STICK_TEST_ONLY_SETTING"] == "1"
    assert "STICK_TEST_ONLY_SETTING" in result.output


def test_cli_is_quiet_without_a_file() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "using" not in result.output


def test_example_covers_every_provider() -> None:
    text = EXAMPLE.read_text()
    for provider, endpoint in models.ENDPOINTS.items():
        if endpoint.kind == "script":
            continue
        assert f"STICK_{provider.upper().replace('-', '_')}_BASE_URL=" in text, provider
        if endpoint.api_key_env:
            assert f"{endpoint.api_key_env}=" in text, provider
        if endpoint.base_url:  # the default shown is the real default
            assert endpoint.base_url in text, provider


def test_example_sets_nothing_and_holds_no_key() -> None:
    text = EXAMPLE.read_text()
    assert dotenv.parse(text) == {}  # every line is a comment: copying it changes nothing
    assert not re.search(r"sk-[A-Za-z0-9]", text)
