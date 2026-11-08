"""Read device state for grading, independently of whatever path the agent used.

The grader goes straight into the containers (`docker exec`), so a broken SSH or API path on the
agent's side can't hide or fake state. Verified: this returns byte-identical config to SSH.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Literal, Protocol

import yaml

from llm_on_a_stick import paths

NodeOS = Literal["srlinux", "frr", "host"]
ConfigFormat = Literal["flat", "tree"]


class LabStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Node:
    name: str
    os: NodeOS
    mgmt_ipv4: str
    container: str


class LabState(Protocol):
    def nodes(self) -> dict[str, Node]: ...
    def running_config(self, node: str, fmt: ConfigFormat = "flat") -> str: ...
    def bgp_sessions(self, node: str) -> dict[str, str]: ...


def load_nodes(topology: str = "base") -> dict[str, Node]:
    path = paths.topology_path(topology)
    topo = yaml.safe_load(path.read_text(encoding="utf-8"))
    lab = topo["name"]
    nodes = {}
    for name, node in topo["topology"]["nodes"].items():
        os_ = (node.get("labels") or {}).get("stick-os")
        if os_ not in ("srlinux", "frr", "host"):
            raise LabStateError(f"node {name} needs a `stick-os` label (srlinux | frr | host)")
        nodes[name] = Node(name, os_, node.get("mgmt-ipv4", ""), f"clab-{lab}-{name}")
    return nodes


class DockerLabState:
    def __init__(self, topology: str = "base") -> None:
        self._nodes = load_nodes(topology)

    def nodes(self) -> dict[str, Node]:
        return self._nodes

    def _node(self, name: str) -> Node:
        if name not in self._nodes:
            raise LabStateError(f"unknown node {name!r}; known: {', '.join(self._nodes)}")
        return self._nodes[name]

    def _exec(self, node: Node, *cmd: str) -> str:
        try:
            res = subprocess.run(
                ["docker", "exec", node.container, *cmd],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise LabStateError(f"{node.name}: {exc}") from exc
        if res.returncode != 0:
            raise LabStateError(
                f"{node.name}: `{' '.join(cmd)}` failed: {(res.stderr or res.stdout).strip()[:300]}"
            )
        return res.stdout

    def running_config(self, node: str, fmt: ConfigFormat = "flat") -> str:
        n = self._node(node)
        if n.os == "srlinux":
            return self._exec(n, "sr_cli", "-d", "info flat" if fmt == "flat" else "info")
        if n.os == "frr":
            return self._exec(n, "vtysh", "-c", "show running-config")
        raise LabStateError(f"{node} is a host; it has no running config")

    def bgp_sessions(self, node: str) -> dict[str, str]:
        """peer address -> session state, lower-cased (established, active, idle, ...)."""
        n = self._node(node)
        if n.os == "srlinux":
            raw = self._exec(
                n, "sr_cli", "-d",
                "info from state network-instance default protocols bgp neighbor * session-state | as json",
            )  # fmt: skip
            data = json.loads(raw) if raw.strip() else {}
            return {
                nb["peer-address"]: str(nb.get("session-state", "")).lower()
                for nb in data.get("neighbor", [])
            }
        if n.os == "frr":
            data = json.loads(self._exec(n, "vtysh", "-c", "show bgp summary json"))
            peers = data.get("ipv4Unicast", {}).get("peers", {})
            return {peer: str(p.get("state", "")).lower() for peer, p in peers.items()}
        raise LabStateError(f"{node} is a host; it has no BGP")
