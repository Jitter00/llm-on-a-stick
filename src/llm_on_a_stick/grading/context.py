"""What a check can see: the run, the live lab, the baseline and the services."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_on_a_stick import services
from llm_on_a_stick.grading.labstate import LabState
from llm_on_a_stick.grading.run import RunInfo
from llm_on_a_stick.services.seed import RestClient, RestError


class ServiceUnavailable(RuntimeError):
    pass


class Services:
    """HTTP access to the tool stack, created lazily (a task that needs no service needs none running)."""

    def __init__(self) -> None:
        self._netbox: RestClient | None = None

    def netbox(self) -> RestClient:
        if self._netbox is None:
            spec = services.load("netbox")
            if spec.seed is None:
                raise ServiceUnavailable("netbox service.yaml has no API settings")
            self._netbox = RestClient(spec.seed.base_url, spec.seed.headers)
        return self._netbox

    def oxidized(self, path: str) -> Any:
        base = services.load("oxidized").health.url.rsplit("/", 1)[0]
        url = f"{base}/{path.lstrip('/')}"
        if not url.startswith(("http://", "https://")):
            raise ServiceUnavailable(f"bad Oxidized URL {url}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 (scheme checked)
                body = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            raise ServiceUnavailable(f"Oxidized not reachable at {base}: {exc}") from exc
        return json.loads(body) if urllib.parse.urlparse(url).path.endswith(".json") else body


@dataclass
class GradeContext:
    run: RunInfo
    lab: LabState
    services: Services = field(default_factory=Services)

    def workspace_file(self, path: str) -> Path:
        """Resolve a path the task asked the agent to write, refusing anything outside the workspace."""
        root = self.run.workspace.resolve()
        target = (root / path).resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"path {path!r} escapes the workspace")
        return target

    def baseline_config(self, node: str) -> str | None:
        path = self.run.baseline_dir / f"{node}.cfg"
        return path.read_text(encoding="utf-8") if path.exists() else None


__all__ = ["GradeContext", "RestError", "ServiceUnavailable", "Services"]
