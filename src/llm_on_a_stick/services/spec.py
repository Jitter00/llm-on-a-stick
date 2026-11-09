"""service.yaml model and discovery."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field

from llm_on_a_stick import paths

_VAR = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def expand(value: Any, env: dict[str, str] | None = None) -> Any:
    """Expand ${VAR} / ${VAR:-default} in every string, like docker compose does."""
    env = dict(os.environ) if env is None else env
    if isinstance(value, str):
        return _VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, list):
        return [expand(v, env) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, env) for k, v in value.items()}
    return value


class Health(BaseModel):
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class Seed(BaseModel):
    kind: Literal["netbox-rest", "rest"]  # "rest": the same seeder for any REST API (NetBox, Nautobot)
    file: str
    base_url: str
    headers: dict[str, str] = Field(default_factory=dict)


class ExecStep(BaseModel):
    service: str
    cmd: list[str]


class PostgresSnapshot(BaseModel):
    """Baseline = a pg_dump taken after seeding; reset = pg_restore it."""

    kind: Literal["postgres"]
    service: str
    database: str
    user: str
    path: str
    stop: list[str] = Field(default_factory=list)
    after_restore: list[ExecStep] = Field(default_factory=list)


class VolumesSnapshot(BaseModel):
    """Baseline = empty volumes; reset = delete them and recreate the services (e.g. Oxidized's repo)."""

    kind: Literal["volumes"]
    services: list[str]
    volumes: list[str]


Snapshot = Annotated[PostgresSnapshot | VolumesSnapshot, Field(discriminator="kind")]


class ServiceSpec(BaseModel):
    name: str
    description: str
    compose: str = "compose.yaml"
    project: str
    wait_timeout_s: int = 300
    health: Health
    endpoints: dict[str, str] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
    seed: Seed | None = None
    snapshot: Snapshot | None = None
    directory: Path = Path()

    @property
    def compose_file(self) -> Path:
        return self.directory / self.compose

    @property
    def seed_file(self) -> Path | None:
        return self.directory / self.seed.file if self.seed else None


def services_dir() -> Path:
    return paths.assets_root() / "services"


def available() -> list[str]:
    root = services_dir()
    return sorted(p.parent.name for p in root.glob("*/service.yaml")) if root.is_dir() else []


def load(name: str, env: dict[str, str] | None = None) -> ServiceSpec:
    path = services_dir() / name / "service.yaml"
    if not path.exists():
        known = ", ".join(available()) or "none"
        raise FileNotFoundError(f"unknown service {name!r} (available: {known})")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec = ServiceSpec.model_validate(expand(raw, env))
    spec.directory = path.parent
    return spec
