from __future__ import annotations

from pathlib import Path

import yaml

from llm_on_a_stick import tasks

VALID = {
    "id": "retrieve-running-config-cli",
    "section": "cfg-mgmt",
    "title": "Retrieve the running config over clear-text CLI",
    "tier": "basic",
    "tags": ["vendor:srl", "iface:cli"],
    "prompt": "Save the full running configuration of {{ node }} to /work/{{ node }}.cfg",
    "requires": {"devices": ["srlinux"], "backend": "containerlab"},
    "canaries": {"bgp_asn": "asn"},
    "checks": [{"type": "file_matches_running_config", "params": {"node": "srl1"}}],
    "allowed_changes": [],
    "limits": {"turns": 30},
}


def write_task(root: Path, data: dict[str, object], dirname: str | None = None) -> Path:
    d = root / str(data.get("section", "x")) / (dirname or str(data["id"]))
    d.mkdir(parents=True)
    path = d / "task.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_valid_task(tmp_path: Path) -> None:
    write_task(tmp_path, VALID)
    found, errors = tasks.lint([tmp_path])
    assert len(found) == 1
    assert errors == []


def test_missing_required_and_bad_enum(tmp_path: Path) -> None:
    bad = {**VALID, "section": "dancing"}
    del bad["checks"]
    write_task(tmp_path, bad, dirname=str(VALID["id"]))
    _, errors = tasks.lint([tmp_path])
    messages = " ".join(e.message for e in errors)
    assert "checks" in messages
    assert "section" in messages


def test_id_must_match_directory(tmp_path: Path) -> None:
    write_task(tmp_path, VALID, dirname="something-else")
    _, errors = tasks.lint([tmp_path])
    assert any("must match its directory" in e.message for e in errors)


def test_missing_oracle_script(tmp_path: Path) -> None:
    write_task(tmp_path, {**VALID, "oracle": "oracle.sh"})
    _, errors = tasks.lint([tmp_path])
    assert any("oracle script" in e.message for e in errors)


def test_unparseable_yaml(tmp_path: Path) -> None:
    d = tmp_path / "cfg-mgmt" / "broken"
    d.mkdir(parents=True)
    (d / "task.yaml").write_text("id: [unclosed", encoding="utf-8")
    _, errors = tasks.lint([tmp_path])
    assert errors
    assert "cannot read YAML" in errors[0].message


def test_empty_root(tmp_path: Path) -> None:
    assert tasks.lint([tmp_path]) == ([], [])
