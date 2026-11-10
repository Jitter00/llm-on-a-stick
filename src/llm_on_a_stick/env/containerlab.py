"""Thin wrapper around the containerlab CLI.

We shell out rather than re-implementing containerlab: it is the source of truth for
lab lifecycle, and its CLI output is what users will see in the docs anyway.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_on_a_stick import paths

DEFAULT_FRR_IMAGE = "stick-frr:dev"


@dataclass
class LabNode:
    name: str
    kind: str
    image: str
    state: str
    mgmt_ipv4: str


class ContainerlabError(RuntimeError):
    pass


def lab_dir_base() -> Path:
    """Where containerlab keeps a lab's working files (``clab-<name>/``, partly owned by root).

    Outside the assets: next to the topology file they would sit inside the source tree or the
    installed package, where files we can't read break the next build or upgrade.
    """
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "stick" / "labs"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("STICK_FRR_IMAGE", DEFAULT_FRR_IMAGE)
    if "CLAB_LABDIR_BASE" not in env:
        base = lab_dir_base()
        base.mkdir(parents=True, exist_ok=True)
        env["CLAB_LABDIR_BASE"] = str(base)
    return env


def _clab(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        res = subprocess.run(
            ["containerlab", *args], capture_output=capture, text=True, env=_env(), check=False
        )
    except FileNotFoundError as exc:
        raise ContainerlabError(
            "containerlab is not installed; see https://containerlab.dev/install/"
        ) from exc
    if res.returncode != 0:
        detail = (res.stderr or "").strip() if capture else ""
        raise ContainerlabError(
            f"containerlab {' '.join(args)} failed (exit {res.returncode}) {detail}".strip()
        )
    return res


def deploy(topology: str, *, reconfigure: bool = False) -> Path:
    topo = paths.topology_path(topology)
    args = ["deploy", "-t", str(topo)]
    if reconfigure:
        args.append("--reconfigure")
    _clab(args)
    return topo


def destroy(topology: str, *, cleanup: bool = True) -> None:
    topo = paths.topology_path(topology)
    args = ["destroy", "-t", str(topo)]
    if cleanup:
        args.append("--cleanup")
    _clab(args)


def parse_inspect(raw: str) -> list[LabNode]:
    """Parse `containerlab inspect --format json`.

    Newer containerlab versions return {"<lab>": [nodes...]}; older ones {"containers": [...]}.
    """
    data: Any = json.loads(raw) if raw.strip() else {}
    if isinstance(data, dict) and "containers" in data:
        items = data["containers"]
    elif isinstance(data, dict):
        items = [n for nodes in data.values() if isinstance(nodes, list) for n in nodes]
    else:
        items = []
    return [
        LabNode(
            name=str(n.get("name", "")),
            kind=str(n.get("kind", "")),
            image=str(n.get("image", "")),
            state=str(n.get("state", "")),
            mgmt_ipv4=str(n.get("ipv4_address", n.get("ipv4-address", ""))),
        )
        for n in items
    ]


def inspect(topology: str) -> list[LabNode]:
    topo = paths.topology_path(topology)
    res = _clab(["inspect", "-t", str(topo), "--format", "json"], capture=True)
    return parse_inspect(res.stdout)


def build_image(name: str, tag: str | None = None) -> str:
    """Build one of our images (e.g. `frr` -> stick-frr:dev) with the local Docker daemon."""
    ctx = paths.image_dir(name)
    tag = tag or f"stick-{name}:dev"
    try:
        res = subprocess.run(["docker", "build", "-t", tag, str(ctx)], check=False)
    except FileNotFoundError as exc:
        raise ContainerlabError("docker is not installed") from exc
    if res.returncode != 0:
        raise ContainerlabError(f"docker build of {name} failed (exit {res.returncode})")
    return tag
