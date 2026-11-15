from __future__ import annotations

from pathlib import Path

import pytest

from llm_on_a_stick import cli, lab


@pytest.fixture(autouse=True)
def _no_local_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests must not pick up the developer's own .env."""
    monkeypatch.setattr(cli, "ENV_FILE", str(tmp_path / "no-such-env-file"))


@pytest.fixture(autouse=True)
def _default_instance(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Unit tests describe lab instance 0, whatever the developer's shell says. The lab tests keep the
    variable: `STICK_INSTANCE=1 uv run pytest -m lab` runs them on a second instance."""
    if request.node.get_closest_marker("lab") is None:
        monkeypatch.delenv(lab.INSTANCE_VAR, raising=False)
