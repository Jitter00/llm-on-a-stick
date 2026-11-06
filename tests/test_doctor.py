from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from llm_on_a_stick import doctor
from llm_on_a_stick.doctor import ContainerlabInfo, DockerInfo, HostInfo


def fake_run(table: dict[str, tuple[int, str, str]]) -> doctor.Runner:
    def run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        code, out, err = table.get(argv[0], (127, "", f"{argv[0]}: command not found"))
        return subprocess.CompletedProcess(argv, code, out, err)

    return run


def host(**kw: Any) -> HostInfo:
    base: dict[str, Any] = {
        "os_family": "linux",
        "arch": "amd64",
        "cpu_count": 8,
        "ram_total_mb": 32768,
        "ram_available_mb": 30000,
        "disk_free_gb": 100.0,
    }
    base.update(kw)
    return HostInfo(**base)


@pytest.mark.parametrize(
    ("raw", "expected"), [("x86_64", "amd64"), ("AMD64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64")]
)
def test_normalise_arch(raw: str, expected: str) -> None:
    assert doctor.normalise_arch(raw) == expected


def test_detect_os_family() -> None:
    assert doctor.detect_os_family("Linux", "Linux version 6.8.0-generic") == "linux"
    assert doctor.detect_os_family("Linux", "Linux version 5.15.153.1-microsoft-standard-WSL2") == "wsl"
    assert doctor.detect_os_family("Darwin") == "macos"
    assert doctor.detect_os_family("Windows") == "windows"


def test_probe_docker_ok() -> None:
    info = {"ServerVersion": "29.9.2", "OperatingSystem": "Ubuntu", "MemTotal": 16 * 1024**3, "NCPU": 4}
    d = doctor.probe_docker(fake_run({"docker": (0, json.dumps(info), "")}))
    assert d.reachable
    assert d.mem_total_mb == 16384
    assert d.ncpu == 4


def test_probe_docker_unreachable() -> None:
    d = doctor.probe_docker(fake_run({"docker": (1, "", "Cannot connect to the Docker daemon\n")}))
    assert not d.reachable
    assert d.error == "Cannot connect to the Docker daemon"


def test_probe_docker_missing_binary() -> None:
    d = doctor.probe_docker(fake_run({}))
    assert not d.reachable
    assert "not found" in (d.error or "")


def test_probe_containerlab() -> None:
    assert doctor.probe_containerlab(fake_run({"containerlab": (0, "0.82.0\n", "")})).version == "0.82.0"
    assert not doctor.probe_containerlab(fake_run({})).installed


def test_probe_model_servers_ollama() -> None:
    def fetch(url: str, timeout: float) -> Any:
        if url.endswith("/api/ps"):
            return {"models": [{"name": "qwen3:32b", "size": 20 * 1024**3, "size_vram": 16 * 1024**3}]}
        return None

    servers = doctor.probe_model_servers(fetch)
    assert [s.name for s in servers] == ["ollama"]
    assert servers[0].loaded_models == ["qwen3:32b"]
    assert servers[0].ram_mb == 4096
    assert servers[0].vram_mb == 16384


def test_probe_model_servers_none() -> None:
    assert doctor.probe_model_servers(lambda url, timeout: None) == []


def test_budget_linux_uses_host_available() -> None:
    b = doctor.compute_budget(host(ram_available_mb=30000), DockerInfo(reachable=True, mem_total_mb=32768))
    assert b.margin_mb == 3000
    assert b.usable_mb == 27000
    assert b.parallel_base_labs == 27000 // b.base_lab_mb


def test_budget_macos_capped_by_docker_vm() -> None:
    b = doctor.compute_budget(
        host(os_family="macos", arch="arm64", ram_available_mb=60000),
        DockerInfo(reachable=True, mem_total_mb=8192),
    )
    assert b.usable_mb == 8192 - 2048


def test_budget_reserve_for_unloaded_model() -> None:
    b = doctor.compute_budget(host(ram_available_mb=30000), DockerInfo(reachable=True), reserve_mb=20000)
    assert b.usable_mb == 7000


def _evaluate(h: HostInfo, docker_ok: bool = True, clab_ok: bool = True, kvm: bool = True) -> Any:
    docker = DockerInfo(reachable=docker_ok, error=None if docker_ok else "no socket")
    clab = ContainerlabInfo(installed=clab_ok, version="0.82.0" if clab_ok else None)
    return doctor.evaluate(h, docker, clab, kvm, doctor.compute_budget(h, docker))


def test_evaluate_full_linux() -> None:
    caps, checks = _evaluate(host(ram_available_mb=64000))
    assert all(c.status == "ok" for c in checks)
    assert caps == {"container_labs": True, "vm_nos": True, "cml_local": True, "all_services_at_once": True}


def test_evaluate_docker_down_is_a_failure() -> None:
    caps, checks = _evaluate(host(), docker_ok=False)
    assert {c.name: c.status for c in checks}["docker"] == "fail"
    assert not caps["container_labs"]


def test_evaluate_apple_silicon_containers_only() -> None:
    caps, checks = _evaluate(host(os_family="macos", arch="arm64", ram_available_mb=16000), kvm=False)
    statuses = {c.name: c.status for c in checks}
    assert statuses["platform"] == "warn"
    assert statuses["image-arch"] == "ok"  # base images are multi-arch
    assert caps["container_labs"]
    assert not caps["vm_nos"]
    assert not caps["cml_local"]


def test_evaluate_native_windows_fails() -> None:
    caps, checks = _evaluate(host(os_family="windows"))
    assert {c.name: c.status for c in checks}["platform"] == "fail"
    assert not caps["container_labs"]


def test_evaluate_not_enough_ram() -> None:
    _, checks = _evaluate(host(ram_available_mb=4000))
    assert {c.name: c.status for c in checks}["ram"] == "fail"


def test_run_doctor_end_to_end_with_fakes() -> None:
    info = {"ServerVersion": "29.9.2", "OperatingSystem": "Ubuntu", "MemTotal": 32 * 1024**3, "NCPU": 8}
    run = fake_run({"docker": (0, json.dumps(info), ""), "containerlab": (0, "0.82.0", "")})
    report = doctor.run_doctor(run=run, fetch=lambda u, t: None, host=host(ram_available_mb=64000))
    assert report.ok
    assert report.to_dict()["ok"] is True
