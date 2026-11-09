"""Canary values: random per run, so a memorised or invented answer can't pass.

A task declares e.g. `canaries: {leaf_desc: description}`; its setup script puts the value on a
device (it gets STICK_CANARY_LEAF_DESC), and checks expect it back via `{{ canaries.leaf_desc }}`.
"""

from __future__ import annotations

import random
import string
from collections.abc import Callable

_KINDS: dict[str, Callable[[random.Random], str]] = {
    "asn": lambda r: str(r.randint(64512, 65534)),  # private 2-byte ASNs
    "ipv4": lambda r: f"198.18.{r.randint(0, 255)}.{r.randint(1, 254)}",  # RFC 2544 benchmarking range
    "description": lambda r: "stick-" + "".join(r.choices(string.hexdigits.lower()[:16], k=8)),
    "hostname": lambda r: "stick-" + "".join(r.choices(string.ascii_lowercase, k=6)),
    # The first three octets of a /24, for pools: "{{ canaries.pool }}.0/24". In 198.19.0.0/16, the other half
    # of the benchmarking range, so it never overlaps an ipv4 canary.
    "net24": lambda r: f"198.19.{r.randint(0, 255)}",
}

KINDS = tuple(_KINDS)


def generate(spec: dict[str, str], seed: int | None = None) -> dict[str, str]:
    rng = random.Random(seed)  # noqa: S311 (not for security: lab test values)
    values: dict[str, str] = {}
    for name, kind in spec.items():
        if kind not in _KINDS:
            raise ValueError(f"canary {name!r}: unknown kind {kind!r} (known: {', '.join(KINDS)})")
        value = _KINDS[kind](rng)
        while value in values.values():  # keep values distinct within a run
            value = _KINDS[kind](rng)
        values[name] = value
    return values


def env_vars(values: dict[str, str]) -> dict[str, str]:
    return {f"STICK_CANARY_{name.upper().replace('-', '_')}": v for name, v in values.items()}
