"""`stick doctor`: inspect the machine and say what this host can run.

Every probe takes injectable `run` / `fetch` callables so it can be unit-tested
without Docker, containerlab or a model server present.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import psutil

from llm_on_a_stick import footprints

Status = Literal["ok", "warn", "fail"]
Runner = Callable[[list[str], float], "subprocess.CompletedProcess[str]"]
Fetcher = Callable[[str, float], Any]

MIB = 1024 * 1024


def default_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: command not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"{argv[0]}: timed out after {timeout}s")


def default_fetch(url: str, timeout: float) -> Any:
    """GET a JSON document; return None if anything goes wrong."""
    if not url.startswith(("http://", "https://")):
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- data


@dataclass
class HostInfo:
    os_family: str  # linux | wsl | macos | windows | other
    arch: str  # amd64 | arm64 | <raw machine>
    cpu_count: int
    ram_total_mb: int
    ram_available_mb: int
    disk_free_gb: float


@dataclass
class DockerInfo:
    reachable: bool
    server_version: str | None = None
    operating_system: str | None = None
    mem_total_mb: int | None = None
    ncpu: int | None = None
    error: str | None = None


@dataclass
class ContainerlabInfo:
    installed: bool
    version: str | None = None
    error: str | None = None


@dataclass
class ModelServer:
    name: str
    url: str
    loaded_models: list[str] = field(default_factory=list)
    ram_mb: int = 0  # loaded model memory resident in system RAM (not VRAM)
    vram_mb: int = 0


@dataclass
class Gpu:
    name: str
    vram_mb: int


@dataclass
class Check:
    name: str
    status: Status
    detail: str


@dataclass
class Budget:
    usable_mb: int
    margin_mb: int
    reserved_mb: int
    base_lab_mb: int
    all_services_mb: int
    parallel_base_labs: int
    all_services_fit_with_one_lab: bool


@dataclass
class Report:
    host: HostInfo
    docker: DockerInfo
    containerlab: ContainerlabInfo
    kvm: bool
    model_servers: list[ModelServer]
    gpus: list[Gpu]
    budget: Budget
    capabilities: dict[str, bool]
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


# --------------------------------------------------------------------------- probes


def normalise_arch(machine: str) -> str:
    m = machine.lower()
    if m in {"x86_64", "amd64"}:
        return "amd64"
    if m in {"aarch64", "arm64"}:
        return "arm64"
    return m


def detect_os_family(system: str | None = None, proc_version: str | None = None) -> str:
    system = system or platform.system()
    if system == "Linux":
        if proc_version is None:
            try:
                proc_version = Path("/proc/version").read_text(encoding="utf-8")
            except OSError:
                proc_version = ""
        return "wsl" if "microsoft" in proc_version.lower() else "linux"
    return {"Darwin": "macos", "Windows": "windows"}.get(system, "other")


def probe_host() -> HostInfo:
    vm = psutil.virtual_memory()
    return HostInfo(
        os_family=detect_os_family(),
        arch=normalise_arch(platform.machine()),
        cpu_count=os.cpu_count() or 1,
        ram_total_mb=vm.total // MIB,
        ram_available_mb=vm.available // MIB,
        disk_free_gb=round(psutil.disk_usage(str(Path.cwd())).free / 1024**3, 1),
    )


def probe_docker(run: Runner = default_run) -> DockerInfo:
    res = run(["docker", "info", "--format", "{{json .}}"], 15)
    if res.returncode != 0:
        lines = (res.stderr or res.stdout).strip().splitlines()
        return DockerInfo(reachable=False, error=lines[-1] if lines else f"exit code {res.returncode}")
    try:
        info = json.loads(res.stdout)
    except ValueError:
        return DockerInfo(reachable=False, error="could not parse `docker info` output")
    if info.get("ServerErrors"):
        return DockerInfo(reachable=False, error="; ".join(info["ServerErrors"]))
    mem = info.get("MemTotal")
    return DockerInfo(
        reachable=True,
        server_version=info.get("ServerVersion"),
        operating_system=info.get("OperatingSystem"),
        mem_total_mb=int(mem) // MIB if mem else None,
        ncpu=info.get("NCPU"),
    )


def probe_containerlab(run: Runner = default_run) -> ContainerlabInfo:
    res = run(["containerlab", "version", "--short"], 15)
    if res.returncode != 0:
        lines = (res.stderr or res.stdout).strip().splitlines()
        return ContainerlabInfo(installed=False, error=lines[-1] if lines else f"exit code {res.returncode}")
    out = res.stdout.strip().splitlines()
    return ContainerlabInfo(installed=True, version=out[-1].strip() if out else None)


def probe_kvm(dev: Path = Path("/dev/kvm")) -> bool:
    return dev.exists() and os.access(dev, os.R_OK | os.W_OK)


def ollama_base() -> str:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host.replace("0.0.0.0", "127.0.0.1")  # noqa: S104 (rewriting, not binding)
    host = host.rstrip("/")
    if urlparse(host).port is None:  # like the ollama CLI: no port means 11434
        host += ":11434"
    return host


def probe_model_servers(fetch: Fetcher = default_fetch) -> list[ModelServer]:
    found: list[ModelServer] = []
    base = ollama_base()
    ps = fetch(f"{base}/api/ps", 2)
    if isinstance(ps, dict):
        server = ModelServer(name="ollama", url=base)
        for m in ps.get("models", []) or []:
            size, vram = int(m.get("size", 0)), int(m.get("size_vram", 0))
            server.loaded_models.append(str(m.get("name", "?")))
            server.ram_mb += max(size - vram, 0) // MIB
            server.vram_mb += vram // MIB
        found.append(server)
    strata = (
        os.environ.get("STICK_STRATA_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/").removesuffix("/v1")
    )
    for name, url in (
        ("lm-studio", "http://127.0.0.1:1234"),
        ("strata / llama.cpp", strata),
        ("openai-compatible", "http://127.0.0.1:8000"),
    ):
        models = fetch(f"{url}/v1/models", 2)
        if isinstance(models, dict) and isinstance(models.get("data"), list):
            found.append(
                ModelServer(name=name, url=url, loaded_models=[str(m.get("id", "?")) for m in models["data"]])
            )
    return found


def probe_gpus(run: Runner = default_run) -> list[Gpu]:
    res = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], 10)
    if res.returncode != 0:
        return []
    gpus = []
    for line in res.stdout.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            gpus.append(Gpu(name=name.strip(), vram_mb=int(mem.strip())))
        except ValueError:
            continue
    return gpus


# --------------------------------------------------------------------------- analysis


def compute_budget(host: HostInfo, docker: DockerInfo, reserve_mb: int = 0) -> Budget:
    """RAM available for labs + services.

    Loaded local models are already excluded from `ram_available_mb`. `reserve_mb` is for
    memory that is *not yet* in use, e.g. an Ollama model that will load on first request.
    On Docker Desktop / OrbStack the Docker VM size caps what containers can use.
    """
    base = host.ram_available_mb
    if docker.mem_total_mb is not None and host.os_family in {"macos", "windows"}:
        base = min(base, docker.mem_total_mb)
    margin = max(2048, base // 10)
    usable = max(base - margin - reserve_mb, 0)
    fp = footprints.load()
    lab = fp.topology_ram_mb("base")
    services = fp.services_ram_mb()
    return Budget(
        usable_mb=usable,
        margin_mb=margin,
        reserved_mb=reserve_mb,
        base_lab_mb=lab,
        all_services_mb=services,
        parallel_base_labs=usable // lab if lab else 0,
        all_services_fit_with_one_lab=usable >= lab + services,
    )


def evaluate(
    host: HostInfo,
    docker: DockerInfo,
    clab: ContainerlabInfo,
    kvm: bool,
    budget: Budget,
) -> tuple[dict[str, bool], list[Check]]:
    checks: list[Check] = []
    fp = footprints.load()

    if host.os_family == "windows":
        checks.append(Check("platform", "fail", "native Windows is not supported; run inside WSL2"))
    elif host.os_family == "macos":
        checks.append(
            Check("platform", "warn", "macOS: containers only (no VM-based NOS, no local CML); best effort")
        )
    elif host.os_family == "wsl":
        checks.append(Check("platform", "ok", "WSL2 (VM-based NOS need nested virtualisation)"))
    else:
        checks.append(Check("platform", "ok", f"{host.os_family}/{host.arch}"))

    if docker.reachable:
        checks.append(Check("docker", "ok", f"{docker.server_version} ({docker.operating_system})"))
    else:
        checks.append(Check("docker", "fail", f"Docker daemon not reachable: {docker.error}"))

    if clab.installed:
        checks.append(Check("containerlab", "ok", clab.version or "installed"))
    else:
        checks.append(
            Check("containerlab", "fail", "containerlab not found; see https://containerlab.dev/install/")
        )

    arch_ok = host.arch in fp.topology_arches("base")
    checks.append(
        Check(
            "image-arch",
            "ok" if arch_ok else "fail",
            f"base topology images available for {host.arch}"
            if arch_ok
            else f"no images for {host.arch} in the base topology",
        )
    )

    vm_nos = kvm and host.arch == "amd64"
    checks.append(
        Check(
            "kvm",
            "ok" if vm_nos else "warn",
            "KVM available (VM-based NOS and local CML possible)"
            if vm_nos
            else "no usable KVM: VM-based NOS (vJunos, Cat8kv) and local CML are unavailable",
        )
    )

    if budget.parallel_base_labs == 0:
        checks.append(
            Check("ram", "fail", f"{budget.usable_mb} MiB usable; base lab needs ~{budget.base_lab_mb} MiB")
        )
    elif not budget.all_services_fit_with_one_lab:
        checks.append(
            Check(
                "ram", "warn", "base lab fits, but not every service at once; services will start on demand"
            )
        )
    else:
        checks.append(
            Check(
                "ram",
                "ok",
                f"{budget.usable_mb} MiB usable, ~{budget.parallel_base_labs} base labs in parallel",
            )
        )

    container_labs = docker.reachable and clab.installed and arch_ok and host.os_family != "windows"
    capabilities = {
        "container_labs": container_labs,
        "vm_nos": container_labs and vm_nos,
        "cml_local": vm_nos,
        "all_services_at_once": container_labs and budget.all_services_fit_with_one_lab,
    }
    return capabilities, checks


def run_doctor(
    run: Runner = default_run,
    fetch: Fetcher = default_fetch,
    reserve_mb: int = 0,
    host: HostInfo | None = None,
) -> Report:
    host = host or probe_host()
    docker = probe_docker(run)
    clab = probe_containerlab(run)
    kvm = probe_kvm()
    budget = compute_budget(host, docker, reserve_mb)
    capabilities, checks = evaluate(host, docker, clab, kvm, budget)
    return Report(
        host=host,
        docker=docker,
        containerlab=clab,
        kvm=kvm,
        model_servers=probe_model_servers(fetch),
        gpus=probe_gpus(run),
        budget=budget,
        capabilities=capabilities,
        checks=checks,
    )
