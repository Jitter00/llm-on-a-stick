"""The PCIe link of the machine's GPUs: is it as fast as it can be while a local model is working?

A link that trained (or fell back) to a lower speed makes a model that moves data between RAM and the GPU
several times slower, with no error anywhere: a run then takes hours and its times mean nothing. Linux says
what each link does and can do in /sys/bus/pci/devices/<address>/, for any vendor and without root.

- What a link can reach is the lower of what its two ends can do (a Gen5 card in a Gen4 slot: Gen4), over
  every hop from the card up to the root port.
- An idle link may run slow to save power, so only readings taken while a model request is in flight count,
  and of those the best one.
- With several GPUs one that reached its speed is enough: a card that isn't used stays idle.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import re
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SYSFS = Path("/sys/bus/pci/devices")
ENV_OFF = "STICK_NO_GPU_LINK_CHECK"  # set by --no-gpu-link-check: record and warn, don't stop the run
SETTLE_S = 2.0  # into a request before the first reading: the link needs a moment to come out of idle
STEP_S = 1.0
MIN_SAMPLES = 3  # fewer readings under load than this: no verdict

_ADDRESS = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$")
_SPEED = re.compile(r"^\s*([0-9.]+)\s*GT/s")


@dataclass(frozen=True)
class Link:
    """One GPU's link now: the slowest hop between the card and the root port, and what it can reach."""

    address: str
    gts: float
    expected_gts: float
    width: int
    expected_width: int

    @property
    def full(self) -> bool:
        return self.gts >= self.expected_gts and self.width >= self.expected_width


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return ""


def _speed(path: Path) -> float | None:
    found = _SPEED.match(_text(path))
    return float(found.group(1)) if found else None


def _width(path: Path) -> int | None:
    text = _text(path)
    return int(text) if text.isdigit() and int(text) > 0 else None


def find_gpus(sysfs: Path = SYSFS) -> list[str]:
    """PCI addresses of the display controllers that sit on a PCIe link (an integrated GPU has none)."""
    if not sysfs.is_dir():
        return []  # not Linux
    found = []
    for dev in sorted(sysfs.iterdir()):
        if _text(dev / "class").startswith("0x03") and _speed(dev / "max_link_speed") is not None:
            found.append(dev.name)
    return found


def _chain(address: str, sysfs: Path) -> list[Path]:
    """The device and every PCI device above it, up to the root port, that reports a link."""
    hops = []
    node = (sysfs / address).resolve()
    while _ADDRESS.match(node.name):
        if _speed(node / "max_link_speed") is not None:
            hops.append(node)
        node = node.parent
    return hops


def read(address: str, sysfs: Path = SYSFS) -> Link | None:
    """The link of one GPU, or None when it can't be read."""
    hops = _chain(address, sysfs)
    now = [v for h in hops if (v := _speed(h / "current_link_speed")) is not None]
    most = [v for h in hops if (v := _speed(h / "max_link_speed")) is not None]
    width = [v for h in hops if (v := _width(h / "current_link_width")) is not None]
    max_width = [v for h in hops if (v := _width(h / "max_link_width")) is not None]
    if not (now and most and width and max_width):
        return None
    return Link(address, min(now), min(most), min(width), min(max_width))


def is_this_host(base_url: str) -> bool:
    """Does this address belong to this machine? (A model server elsewhere has its own GPU.)"""
    host = urlparse(base_url if "//" in base_url else f"//{base_url}").hostname or ""
    if not host:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(str(address).split("%")[0])
        if ip.is_loopback:
            return True
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as probe:
                probe.bind((str(ip), 0))  # only an address of one of our own interfaces can be bound
            return True
        except OSError:
            continue
    return False


def enforced() -> bool:
    """Stop a run on a degraded link? (False with --no-gpu-link-check: record and warn only.)"""
    return os.environ.get(ENV_OFF, "") not in ("1", "true", "yes")


class Sampler:
    """Reads the GPUs' links while a model request is in flight and keeps the best reading of each."""

    def __init__(self, sysfs: Path = SYSFS, settle_s: float = SETTLE_S, step_s: float = STEP_S) -> None:
        self.sysfs, self.settle_s, self.step_s = sysfs, settle_s, step_s
        self.gpus = find_gpus(sysfs)
        self.best: dict[str, Link] = {}
        self.samples = 0
        self._busy = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self) -> None:
        """One reading of every GPU (the thread calls this; tests call it directly)."""
        seen = False
        for address in self.gpus:
            link = read(address, self.sysfs)
            if link is None:
                continue
            seen = True
            best = self.best.get(address)
            if best is None or (link.gts, link.width) > (best.gts, best.width):
                self.best[address] = link
        self.samples += seen

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._busy.wait(0.2):
                continue
            began = time.monotonic()
            while self._busy.is_set() and not self._stop.is_set():
                if time.monotonic() - began >= self.settle_s:
                    self.sample()
                self._stop.wait(self.step_s)

    @contextlib.contextmanager
    def busy(self) -> Iterator[None]:
        """Around one model request."""
        if self.gpus and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="gpu-link", daemon=True)
            self._thread.start()
        self._busy.set()
        try:
            yield
        finally:
            self._busy.clear()

    def close(self) -> None:
        self._stop.set()
        self._busy.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def summary(self) -> dict[str, Any] | None:
        """For metrics.json. None when there was nothing to read (no PCIe GPU, not Linux)."""
        if not self.gpus:
            return None
        links = [self.best[a] for a in self.gpus if a in self.best]
        judged = self.samples >= MIN_SAMPLES and bool(links)
        return {
            "samples": self.samples,
            "degraded": judged and not any(link.full for link in links),
            "gpus": [
                {
                    "address": link.address,
                    "peak_gts": link.gts,
                    "expected_gts": link.expected_gts,
                    "width": link.width,
                    "expected_width": link.expected_width,
                }
                for link in links
            ],
        }


def describe(summary: dict[str, Any]) -> str:
    """One sentence about a degraded reading, naming the slowest card."""
    parts = []
    for g in summary.get("gpus", []):
        if g["peak_gts"] < g["expected_gts"]:
            can = f"its link can do {g['expected_gts']:g} GT/s"
            parts.append(f"GPU {g['address']} ran at {g['peak_gts']:g} GT/s, {can}")
        elif g["width"] < g["expected_width"]:
            parts.append(f"GPU {g['address']} ran at x{g['width']}, its link can do x{g['expected_width']}")
    return "; ".join(parts)


__all__ = ["ENV_OFF", "Link", "Sampler", "describe", "enforced", "find_gpus", "is_this_host", "read"]
