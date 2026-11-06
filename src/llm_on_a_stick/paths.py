"""Locate lab assets (topologies, configs, images, sections).

In a source checkout they live at the repo root. In an installed wheel they are shipped
under ``llm_on_a_stick/_assets``. ``STICK_HOME`` overrides both.
"""

from __future__ import annotations

import os
from pathlib import Path

ASSET_DIRS = ("topologies", "configs", "images", "sections")
_PACKAGE_DIR = Path(__file__).resolve().parent


def assets_root() -> Path:
    override = os.environ.get("STICK_HOME")
    if override:
        return Path(override).expanduser().resolve()
    bundled = _PACKAGE_DIR / "_assets"
    if bundled.is_dir():
        return bundled
    # src/llm_on_a_stick/paths.py -> repo root is two levels above the package dir
    return _PACKAGE_DIR.parents[1]


def topology_path(name: str) -> Path:
    """Resolve a built-in topology name (``base``) or a path to a ``.clab.yml`` file."""
    candidate = Path(name)
    if candidate.suffix in {".yml", ".yaml"} and candidate.exists():
        return candidate.resolve()
    builtin = assets_root() / "topologies" / f"{name}.clab.yml"
    if builtin.exists():
        return builtin
    raise FileNotFoundError(f"topology {name!r} not found (looked for {builtin})")


def image_dir(name: str) -> Path:
    path = assets_root() / "images" / name
    if not (path / "Dockerfile").exists():
        raise FileNotFoundError(f"image {name!r} not found (looked for {path}/Dockerfile)")
    return path


def sections_dir() -> Path:
    return assets_root() / "sections"
