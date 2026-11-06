"""Idempotent REST seeding (NetBox-style APIs)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class SeedEntry(BaseModel):
    endpoint: str
    lookup: str
    data: dict[str, Any]


@dataclass
class SeedResult:
    created: list[str]
    existing: list[str]


class RestError(RuntimeError):
    pass


class RestClient:
    def __init__(self, base_url: str, headers: dict[str, str], timeout: float = 30) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"base_url must be http(s): {base_url}")
        self.base_url = base_url.rstrip("/") + "/"
        self.headers = {"Accept": "application/json", "Content-Type": "application/json", **headers}
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None) -> Any:
        url = urllib.parse.urljoin(self.base_url, path.lstrip("/"))
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (scheme checked)
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RestError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RestError(f"{method} {url} failed: {exc.reason}") from exc
        return json.loads(payload) if payload else None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self.request("POST", path, body)


def load_entries(path: Path) -> list[SeedEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [SeedEntry.model_validate(e) for e in raw]


def apply(client: RestClient, entries: list[SeedEntry]) -> SeedResult:
    result = SeedResult(created=[], existing=[])
    for e in entries:
        value = e.data[e.lookup]
        label = f"{e.endpoint}/{value}"
        query = urllib.parse.urlencode({e.lookup: value})
        found = client.get(f"{e.endpoint.strip('/')}/?{query}")
        if found and found.get("count", 0) > 0:
            result.existing.append(label)
            continue
        client.post(f"{e.endpoint.strip('/')}/", e.data)
        result.created.append(label)
    return result
