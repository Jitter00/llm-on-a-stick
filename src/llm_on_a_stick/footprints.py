"""RAM footprint estimates for images, topologies and services."""

from __future__ import annotations

from functools import cache
from importlib.resources import files

import yaml
from pydantic import BaseModel, Field


class ImageFootprint(BaseModel):
    image: str
    ram_mb: int = Field(gt=0)
    arch: list[str]
    measured: bool = False


class TopologyFootprint(BaseModel):
    nodes: dict[str, int]


class ServiceFootprint(BaseModel):
    ram_mb: int = Field(gt=0)
    measured: bool = False


class Footprints(BaseModel):
    images: dict[str, ImageFootprint]
    topologies: dict[str, TopologyFootprint]
    services: dict[str, ServiceFootprint]

    def topology_ram_mb(self, name: str) -> int:
        topo = self.topologies[name]
        return sum(self.images[img].ram_mb * count for img, count in topo.nodes.items())

    def services_ram_mb(self, names: list[str] | None = None) -> int:
        selected = self.services if names is None else {n: self.services[n] for n in names}
        return sum(s.ram_mb for s in selected.values())

    def topology_arches(self, name: str) -> set[str]:
        """Architectures every image in the topology supports."""
        sets = [set(self.images[img].arch) for img in self.topologies[name].nodes]
        return set.intersection(*sets) if sets else set()


@cache
def load() -> Footprints:
    raw = files("llm_on_a_stick").joinpath("data/footprints.yaml").read_text(encoding="utf-8")
    return Footprints.model_validate(yaml.safe_load(raw))
