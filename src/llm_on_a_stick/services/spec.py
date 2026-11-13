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
    """Healthy = `url` answers 2xx. For an API that answers 200 with an error inside (JSON-RPC: Zabbix),
    `post` is sent as the JSON body and the answer must contain the text `expect`."""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    post: dict[str, Any] | None = None
    expect: str | None = None


class Seed(BaseModel):
    kind: Literal["netbox-rest", "rest"]  # "rest": the same seeder for any REST API (NetBox, Nautobot)
    file: str
    base_url: str
    headers: dict[str, str] = Field(default_factory=dict)


class Api(BaseModel):
    """The service's REST API, for the grader and task scripts, when no seed carries the same settings."""

    base_url: str
    headers: dict[str, str] = Field(default_factory=dict)


class ExecStep(BaseModel):
    service: str
    cmd: list[str]


class Init(BaseModel):
    """One-time setup that compose can't express (an admin user, an API token, settings): commands run in
    the service's containers after the first boot, while the service isn't healthy yet, then a restart."""

    steps: list[ExecStep]
    restart: list[str] = Field(default_factory=list)


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


class HttpSnapshot(BaseModel):
    """Baseline = the empty service; reset = one HTTP request to it (e.g. moto's /moto-api/reset)."""

    kind: Literal["http"]
    url: str
    method: Literal["POST", "PUT", "DELETE"] = "POST"


class MysqlSnapshot(BaseModel):
    """Baseline = a mariadb-dump taken after init; reset = load it back (MariaDB/MySQL services)."""

    kind: Literal["mysql"]
    service: str
    database: str
    user: str
    password: str
    path: str
    stop: list[str] = Field(default_factory=list)
    after_restore: list[ExecStep] = Field(default_factory=list)


Snapshot = Annotated[
    PostgresSnapshot | VolumesSnapshot | HttpSnapshot | MysqlSnapshot, Field(discriminator="kind")
]


class McpServer(BaseModel):
    """The MCP server a model reaches this service through: one of the upstream servers
    in the stick-mcp image (images/mcp), started for each attempt with this environment."""

    server: str  # its name in the image: `docker run stick-mcp:dev <server>`
    version: str  # the upstream version in the image, for the record (the image pins it)
    env: dict[str, str] = Field(default_factory=dict)
    # The tools the model is shown, by the server's names. Empty: all of them. Large servers are cut down to
    # what an engineer would use, so that the tool list fits small context windows.
    allow: list[str] = Field(default_factory=list)


class ServiceSpec(BaseModel):
    name: str
    description: str
    compose: str = "compose.yaml"
    project: str
    wait_timeout_s: int = 300
    health: Health
    endpoints: dict[str, str] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
    # Environment variables that point client tools at the service (e.g. AWS_ENDPOINT_URL for moto). The
    # toolbox and the setup/oracle scripts of a task that requires the service get them.
    env: dict[str, str] = Field(default_factory=dict)
    seed: Seed | None = None
    api: Api | None = None
    init: Init | None = None
    snapshot: Snapshot | None = None
    mcp: McpServer | None = None
    directory: Path = Path()

    @property
    def compose_file(self) -> Path:
        return self.directory / self.compose

    @property
    def api_settings(self) -> Api | None:
        """Where the REST API is and how to authenticate: `api:`, else what the seed uses."""
        if self.api is not None:
            return self.api
        return Api(base_url=self.seed.base_url, headers=self.seed.headers) if self.seed else None

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
