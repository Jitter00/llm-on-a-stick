"""Compare a config an agent produced with what the device actually runs.

Lines are compared as a multiset after light normalisation (whitespace, comment/banner lines), so
ordering differences don't count but missing or invented lines do.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

_FRR_NOISE = re.compile(r"^(!.*|Building configuration\.\.\.|Current configuration:|end)$")


def normalise(text: str, os_: str, ignore: Iterable[str] = ()) -> list[str]:
    patterns = [re.compile(p) for p in ignore]
    out = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if os_ == "frr" and _FRR_NOISE.match(line):
            continue
        if any(p.search(line) for p in patterns):
            continue
        out.append(line)
    return out


@dataclass
class ConfigDiff:
    expected_lines: int
    observed_lines: int
    missing: list[str]  # on the device, not in the output
    extra: list[str]  # in the output, not on the device

    @property
    def identical(self) -> bool:
        return not self.missing and not self.extra

    @property
    def overlap(self) -> float:
        """Share of the device's lines that the output got right."""
        if not self.expected_lines:
            return 1.0
        return (self.expected_lines - len(self.missing)) / self.expected_lines


def compare(expected: list[str], observed: list[str]) -> ConfigDiff:
    exp, obs = Counter(expected), Counter(observed)
    missing = list((exp - obs).elements())
    extra = list((obs - exp).elements())
    return ConfigDiff(len(expected), len(observed), missing, extra)
