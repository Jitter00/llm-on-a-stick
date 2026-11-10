from __future__ import annotations

from pathlib import Path

import pytest

from llm_on_a_stick import cli


@pytest.fixture(autouse=True)
def _no_local_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests must not pick up the developer's own .env."""
    monkeypatch.setattr(cli, "ENV_FILE", str(tmp_path / "no-such-env-file"))
