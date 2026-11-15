"""What one lab instance is called and where it lives: names, addresses, ports.

A machine can run several instances side by side: each is a lab plus its own copy of the services. The
instance is one number, `STICK_INSTANCE` (`stick --instance N`), 0 unless set. Instance 0 is the lab as the
docs describe it (`stick-base`, 172.30.30.0/24, ports 8081...). Instance N has `stickN` in every name, the
subnet 172.30.<30+N>.0/24 with the same host numbers, and every host port + 100*N.

The topology, compose and service files carry instance 0's values as defaults of environment variables
(`${STICK_NAME:-stick}`, `${STICK_MGMT_PREFIX:-172.30.30}`, `${STICK_NETBOX_PORT:-8081}`); `env()` sets
those variables for another instance. Files read by a tool that can't expand variables (SR Linux startup
configs, Oxidized's router list...) are copied with the addresses replaced: `render_instance_files()`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from llm_on_a_stick import paths

INSTANCE_VAR = "STICK_INSTANCE"
MAX_INSTANCES = 4  # with ports + 100*N, a fifth instance would reach ports other tools commonly use
BASE_NAME = "stick"
BASE_PREFIX = "172.30.30"  # instance 0's management subnet, without the host number

# Host number of each service on the management network (lab nodes use .11-.99).
SERVICE_HOSTS = {
    "netbox": 100,
    "oxidized": 101,
    "nautobot": 102,
    "moto": 103,
    "librenms": 104,
    "zabbix": 106,
    "loki": 108,  # Alloy, the syslog receiver; Loki and Grafana are reached from the host
    "telemetry": 109,  # gNMIc, which subscribes to the SR Linux routers
    "gitea": 112,
    "powerdns": 113,
}
# Further containers of a service that need the management network (LibreNMS's dispatcher polls from it;
# Zabbix's server polls from the first address, its web frontend has the API).
SERVICE_EXTRA_HOSTS = {
    "librenms": [105],
    "zabbix": [107],
    "loki": [111],  # Grafana, which reads the telemetry service's Prometheus over this network
    "telemetry": [110],  # Prometheus
}

# Host ports of instance 0, by the variable the compose and service files read (a test compares them).
PORTS = {
    "STICK_NETBOX_PORT": 8081,
    "STICK_NAUTOBOT_PORT": 8082,
    "STICK_MOTO_PORT": 8083,
    "STICK_LIBRENMS_PORT": 8084,
    "STICK_ZABBIX_PORT": 8085,
    "STICK_GRAFANA_PORT": 8086,
    "STICK_LOKI_PORT": 8087,
    "STICK_PROMETHEUS_PORT": 8088,
    "STICK_GITEA_PORT": 8089,
    "STICK_POWERDNS_PORT": 8090,
    "STICK_DNS_PORT": 8091,
    "STICK_OXIDIZED_PORT": 8888,
}

# Files that hold management addresses and are read by a tool that can't expand variables: the variable
# that names the copy to use (a file or a directory), and the path below the assets.
RENDERED = {
    "STICK_SRL_CONFIGS": "configs/srl",
    "STICK_OXIDIZED_ROUTER_DB": "services/oxidized/router.db",
    "STICK_GNMIC_CONFIG": "services/telemetry/gnmic.yaml",
    "STICK_GRAFANA_DATASOURCES": "services/loki/grafana/datasources.yaml",
}


class InstanceError(RuntimeError):
    pass


def instance(environ: Mapping[str, str] | None = None) -> int:
    """The instance this process works on: `STICK_INSTANCE`, 0 when unset."""
    raw = (os.environ if environ is None else environ).get(INSTANCE_VAR, "").strip() or "0"
    if not raw.isdigit() or int(raw) >= MAX_INSTANCES:
        raise InstanceError(f"{INSTANCE_VAR} must be a number from 0 to {MAX_INSTANCES - 1}, not {raw!r}")
    return int(raw)


def _n(n: int | None) -> int:
    return instance() if n is None else n


def name(n: int | None = None) -> str:
    """The prefix of everything the instance creates: `stick`, `stick1`, ..."""
    return BASE_NAME if _n(n) == 0 else f"{BASE_NAME}{_n(n)}"


def mgmt_prefix(n: int | None = None) -> str:
    first, second, third = BASE_PREFIX.split(".")
    return f"{first}.{second}.{int(third) + _n(n)}"


def mgmt_network(n: int | None = None) -> str:
    return f"{name(n)}-mgmt"


def mgmt_subnet(n: int | None = None) -> str:
    return f"{mgmt_prefix(n)}.0/24"


def service_ip(service: str, n: int | None = None) -> str:
    return f"{mgmt_prefix(n)}.{SERVICE_HOSTS[service]}"


def service_ips(service: str, n: int | None = None) -> list[str]:
    """Every management address of a service, in the order of its containers in compose.yaml."""
    hosts = [SERVICE_HOSTS[service], *SERVICE_EXTRA_HOSTS.get(service, [])]
    return [f"{mgmt_prefix(n)}.{host}" for host in hosts]


def state_dir(n: int | None = None) -> Path:
    """Where an instance keeps its lock and its copies of the address-bearing files."""
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "stick" / "instances" / str(_n(n))


def env(base: Mapping[str, str] | None = None, n: int | None = None) -> dict[str, str]:
    """The environment for everything that reads the instance's files (containerlab, docker compose, the
    service.yaml loader, task scripts). Instance 0: `base` as it is, so the files' defaults apply and a
    port the user moved stays moved. Instance N: the derived values, whatever `base` says."""
    out = dict(os.environ if base is None else base)
    n = _n(n)
    if n == 0:
        return out
    out[INSTANCE_VAR] = str(n)
    out["STICK_NAME"] = name(n)
    out["STICK_MGMT_PREFIX"] = mgmt_prefix(n)
    for var, port in PORTS.items():
        out[var] = str(port + 100 * n)
    for var, rel in RENDERED.items():
        out[var] = str(state_dir(n) / "files" / rel)
    return out


def render_instance_files(n: int | None = None) -> list[Path]:
    """Write the instance's copies of the files in RENDERED, with its management addresses. Instance 0
    uses the originals: nothing is written."""
    n = _n(n)
    if n == 0:
        return []
    old, new = f"{BASE_PREFIX}.", f"{mgmt_prefix(n)}."
    written = []
    for rel in RENDERED.values():
        source = paths.assets_root() / rel
        target = state_dir(n) / "files" / rel
        for src in sorted(source.rglob("*")) if source.is_dir() else [source]:
            if not src.is_file():
                continue
            dst = target / src.relative_to(source) if source.is_dir() else target
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(src.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
            written.append(dst)
    return written


@contextmanager
def lock(n: int | None = None) -> Iterator[None]:
    """Hold the instance for one user (a run, a validation, the lab tests): they reset the lab and the
    services, so a second one on the same instance would spoil both. Fails at once if it is taken."""
    import fcntl  # not on Windows, where there is no lab either

    n = _n(n)
    path = state_dir(n) / "lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            other = (n + 1) % MAX_INSTANCES
            raise InstanceError(
                f"lab instance {n} is in use by another stick command. Wait for it, or use another "
                f"instance: `stick --instance {other} ...` ({INSTANCE_VAR}={other})"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
