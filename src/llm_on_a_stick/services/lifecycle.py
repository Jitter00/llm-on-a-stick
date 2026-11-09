"""Bring services up/down with docker compose, seed them, snapshot and reset them."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from llm_on_a_stick import lab
from llm_on_a_stick.services import seed as seeding
from llm_on_a_stick.services.spec import (
    HttpSnapshot,
    MysqlSnapshot,
    PostgresSnapshot,
    ServiceSpec,
    VolumesSnapshot,
)


class ServiceError(RuntimeError):
    pass


Log = Callable[[str], None]


def _noop(_: str) -> None:
    return None


def _run(argv: list[str], *, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        res = subprocess.run(argv, capture_output=capture, text=True, check=False)
    except FileNotFoundError as exc:
        raise ServiceError(f"{argv[0]} is not installed") from exc
    if check and res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        tail = " | ".join(detail[-5:])
        raise ServiceError(f"`{' '.join(argv[:6])} ...` failed (exit {res.returncode}): {tail}")
    return res


def compose_argv(spec: ServiceSpec, *args: str) -> list[str]:
    return ["docker", "compose", "-p", spec.project, "-f", str(spec.compose_file), *args]


def ensure_mgmt_network() -> bool:
    """Create the lab management network unless the lab or another service already did.

    Returns True if this call created it.
    """
    if _run(["docker", "network", "inspect", lab.MGMT_NETWORK], check=False).returncode == 0:
        return False
    _run(["docker", "network", "create", "--subnet", lab.MGMT_SUBNET, lab.MGMT_NETWORK])
    return True


def healthy(spec: ServiceSpec, timeout: float = 5) -> bool:
    req = urllib.request.Request(spec.health.url, headers=spec.health.headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL comes from service.yaml)
            return bool(200 <= resp.status < 300)
    except (urllib.error.URLError, OSError):
        return False


def wait_healthy(spec: ServiceSpec, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if healthy(spec):
            return
        time.sleep(3)
    raise ServiceError(f"{spec.name}: not healthy at {spec.health.url} after {timeout:.0f}s")


def has_snapshot(spec: ServiceSpec) -> bool:
    snap = spec.snapshot
    if snap is None:
        return False
    if snap.kind != "postgres":
        return True  # the baseline is "empty", which always exists
    res = _run(compose_argv(spec, "exec", "-T", snap.service, "test", "-f", snap.path), check=False)
    return res.returncode == 0


def _mysql_argv(spec: ServiceSpec, snap: MysqlSnapshot, script: str) -> list[str]:
    """A shell command in the database container, with the credentials in its environment (not its argv)."""
    return compose_argv(
        spec, "exec", "-T", "-e", f"MYSQL_PWD={snap.password}", "-e", f"SNAP_USER={snap.user}",
        "-e", f"SNAP_DB={snap.database}", "-e", f"SNAP_PATH={snap.path}", snap.service, "sh", "-c", script,
    )  # fmt: skip


def take_snapshot(spec: ServiceSpec) -> None:
    snap = spec.snapshot
    if snap is None:
        raise ServiceError(f"{spec.name} has no snapshot configuration")
    if snap.kind == "mysql":
        dump = 'mariadb-dump -u"$SNAP_USER" --single-transaction --skip-lock-tables "$SNAP_DB" > "$SNAP_PATH"'
        _run(_mysql_argv(spec, snap, dump))
        return
    if snap.kind != "postgres":
        raise ServiceError(f"{spec.name}: its baseline is the empty service, there is nothing to snapshot")
    _run(
        compose_argv(
            spec, "exec", "-T", snap.service,
            "pg_dump", "-U", snap.user, "-Fc", "-f", snap.path, snap.database,
        )
    )  # fmt: skip


def _restore_postgres(spec: ServiceSpec, snap: PostgresSnapshot, log: Log) -> None:
    if not has_snapshot(spec):
        raise ServiceError(f"{spec.name}: no snapshot yet; run `stick svc up {spec.name}` first")
    if snap.stop:
        log(f"stopping {', '.join(snap.stop)}")
        _run(compose_argv(spec, "stop", *snap.stop))
    log("restoring database")
    _run(
        compose_argv(
            spec, "exec", "-T", snap.service,
            "pg_restore", "-U", snap.user, "-d", snap.database, "--clean", "--if-exists",
            "--single-transaction", snap.path,
        )
    )  # fmt: skip
    for step in snap.after_restore:
        _run(compose_argv(spec, "exec", "-T", step.service, *step.cmd))


def _restore_mysql(spec: ServiceSpec, snap: MysqlSnapshot, log: Log) -> None:
    if not has_snapshot(spec):
        raise ServiceError(f"{spec.name}: no snapshot yet; run `stick svc up {spec.name}` first")
    if snap.stop:
        log(f"stopping {', '.join(snap.stop)}")
        _run(compose_argv(spec, "stop", *snap.stop))
    log("restoring database")
    _run(_mysql_argv(spec, snap, 'mariadb -u"$SNAP_USER" "$SNAP_DB" < "$SNAP_PATH"'))
    for step in snap.after_restore:
        _run(compose_argv(spec, "exec", "-T", step.service, *step.cmd))


def _restore_volumes(spec: ServiceSpec, snap: VolumesSnapshot, log: Log) -> None:
    log(f"removing {', '.join(snap.services)} and volumes {', '.join(snap.volumes)}")
    _run(compose_argv(spec, "rm", "--stop", "--force", *snap.services))
    for volume in snap.volumes:
        _run(["docker", "volume", "rm", "--force", f"{spec.project}_{volume}"])


def _restore_http(spec: ServiceSpec, snap: HttpSnapshot, log: Log) -> None:
    log(f"{snap.method} {snap.url}")
    req = urllib.request.Request(snap.url, method=snap.method, data=b"")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (URL comes from service.yaml)
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ServiceError(f"{spec.name}: reset request to {snap.url} failed: {exc}") from exc


def restore_snapshot(spec: ServiceSpec, log: Log = _noop) -> None:
    snap = spec.snapshot
    if snap is None:
        raise ServiceError(f"{spec.name} has no snapshot configuration")
    if snap.kind == "http":  # the service keeps running: nothing to start again
        _restore_http(spec, snap, log)
        return
    if snap.kind == "postgres":
        _restore_postgres(spec, snap, log)
    elif snap.kind == "mysql":
        _restore_mysql(spec, snap, log)
        if not snap.stop:  # loaded into the running service: nothing to start again
            wait_healthy(spec, spec.wait_timeout_s)
            return
    else:
        _restore_volumes(spec, snap, log)
    log("starting services")
    _run(compose_argv(spec, "up", "-d", "--wait", "--wait-timeout", str(spec.wait_timeout_s)))
    wait_healthy(spec, spec.wait_timeout_s)


@dataclass
class UpResult:
    network_created: bool
    seeded: seeding.SeedResult | None
    snapshot_taken: bool


def up(spec: ServiceSpec, *, seed: bool = True, log: Log = _noop) -> UpResult:
    created = ensure_mgmt_network()
    if created:
        log(f"created network {lab.MGMT_NETWORK} ({lab.MGMT_SUBNET})")
    log(f"starting {spec.project} (first boot can take a few minutes)")
    _run(compose_argv(spec, "up", "-d", "--wait", "--wait-timeout", str(spec.wait_timeout_s)))
    if spec.init is not None and not healthy(spec):  # first boot: create what compose can't
        log("first boot: creating the admin user, API token and settings")
        for step in spec.init.steps:
            _run(compose_argv(spec, "exec", "-T", step.service, *step.cmd))
        if spec.init.restart:
            _run(compose_argv(spec, "restart", *spec.init.restart))
    wait_healthy(spec, spec.wait_timeout_s)

    result: seeding.SeedResult | None = None
    snapshot_taken = False
    if seed and spec.seed is not None and spec.seed_file is not None:
        client = seeding.RestClient(spec.seed.base_url, spec.seed.headers)
        result = seeding.apply(client, seeding.load_entries(spec.seed_file))
        log(f"seed: {len(result.created)} created, {len(result.existing)} already present")
    if spec.snapshot is not None and not has_snapshot(spec):
        take_snapshot(spec)
        snapshot_taken = True
        log("took baseline snapshot")
    return UpResult(network_created=created, seeded=result, snapshot_taken=snapshot_taken)


def down(spec: ServiceSpec, *, volumes: bool = False) -> None:
    args = ["down", "-t", "10"]
    if volumes:
        args.append("-v")
    _run(compose_argv(spec, *args))


def status(spec: ServiceSpec) -> list[dict[str, str]]:
    res = _run(compose_argv(spec, "ps", "--all", "--format", "json"))
    rows: list[dict[str, str]] = []
    for line in res.stdout.strip().splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        rows.append(
            {
                "service": str(item.get("Service", "")),
                "state": str(item.get("State", "")),
                "health": str(item.get("Health", "")),
            }
        )
    return rows
