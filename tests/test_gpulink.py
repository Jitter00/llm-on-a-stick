from __future__ import annotations

from pathlib import Path

from llm_on_a_stick import gpulink

GPU, VGA = "0x030000", "0x030200"


def device(
    sysfs: Path, chain: list[str], cls: str, now: str, most: str, width: int = 16, max_width: int = 16
) -> None:
    """A PCI device in a fake sysfs: the real tree under devices/, a symlink under bus/ as on Linux."""
    real = sysfs.parent / "devices" / "pci0000:00"
    for name in chain:
        real = real / name
    real.mkdir(parents=True, exist_ok=True)
    (real / "class").write_text(cls + "\n")
    if now:
        (real / "current_link_speed").write_text(f"{now} GT/s PCIe\n")
        (real / "max_link_speed").write_text(f"{most} GT/s PCIe\n")
        (real / "current_link_width").write_text(f"{width}\n")
        (real / "max_link_width").write_text(f"{max_width}\n")
    sysfs.mkdir(parents=True, exist_ok=True)
    link = sysfs / chain[-1]
    if not link.exists():
        link.symlink_to(real)


def machine(tmp_path: Path, now: str, card_max: str = "16.0", port_max: str = "16.0", **kw: int) -> Path:
    sysfs = tmp_path / "bus"
    device(sysfs, ["0000:00:01.0"], "0x060400", now, port_max, **kw)
    device(sysfs, ["0000:00:01.0", "0000:01:00.0"], GPU, now, card_max, **kw)
    return sysfs


def sampled(sysfs: Path, times: int = 3) -> dict:
    s = gpulink.Sampler(sysfs)
    for _ in range(times):
        s.sample()
    summary = s.summary()
    assert summary is not None
    return summary


def test_full_speed_is_fine(tmp_path: Path) -> None:
    summary = sampled(machine(tmp_path, "16.0"))
    assert summary["degraded"] is False
    assert summary["gpus"] == [
        {"address": "0000:01:00.0", "peak_gts": 16.0, "expected_gts": 16.0, "width": 16, "expected_width": 16}
    ]


def test_gen1_under_load_is_degraded(tmp_path: Path) -> None:
    summary = sampled(machine(tmp_path, "2.5"))
    assert summary["degraded"] is True
    assert gpulink.describe(summary) == "GPU 0000:01:00.0 ran at 2.5 GT/s, its link can do 16 GT/s"


def test_a_faster_card_in_a_slower_slot_expects_the_slot(tmp_path: Path) -> None:
    sysfs = machine(tmp_path, "16.0", card_max="32.0", port_max="16.0")  # a Gen5 card in a Gen4 slot
    link = gpulink.read("0000:01:00.0", sysfs)
    assert link is not None and link.expected_gts == 16.0 and link.full
    assert sampled(sysfs)["degraded"] is False


def test_a_narrow_link_is_degraded(tmp_path: Path) -> None:
    summary = sampled(machine(tmp_path, "16.0", width=8))
    assert summary["degraded"] is True
    assert gpulink.describe(summary) == "GPU 0000:01:00.0 ran at x8, its link can do x16"


def test_a_card_behind_its_own_bridge_counts_the_slot_link(tmp_path: Path) -> None:
    sysfs = tmp_path / "bus"
    chain = ["0000:00:01.0", "0000:01:00.0", "0000:02:00.0", "0000:03:00.0"]
    device(sysfs, chain[:1], "0x060400", "2.5", "16.0")  # the slot: stuck
    device(sysfs, chain[:2], "0x060400", "2.5", "16.0")  # the card's upstream port
    device(sysfs, chain[:3], "0x060400", "16.0", "16.0")  # its downstream port
    device(sysfs, chain, GPU, "16.0", "16.0")  # the GPU itself reads full speed
    assert gpulink.find_gpus(sysfs) == ["0000:03:00.0"]
    assert sampled(sysfs)["degraded"] is True


def test_an_integrated_gpu_has_no_link_and_is_skipped(tmp_path: Path) -> None:
    sysfs = tmp_path / "bus"
    device(sysfs, ["0000:00:02.0"], GPU, "", "")
    assert gpulink.find_gpus(sysfs) == []
    assert gpulink.Sampler(sysfs).summary() is None


def test_one_card_at_speed_is_enough(tmp_path: Path) -> None:
    sysfs = machine(tmp_path, "16.0")
    device(sysfs, ["0000:00:03.0"], "0x060400", "2.5", "16.0")
    device(sysfs, ["0000:00:03.0", "0000:04:00.0"], VGA, "2.5", "16.0")  # a second card, idle
    summary = sampled(sysfs)
    assert len(summary["gpus"]) == 2 and summary["degraded"] is False


def test_the_best_reading_counts(tmp_path: Path) -> None:
    sysfs = machine(tmp_path, "2.5")
    s = gpulink.Sampler(sysfs)
    s.sample()
    for name in ("0000:00:01.0", "0000:01:00.0"):
        (sysfs / name / "current_link_speed").write_text("16.0 GT/s PCIe\n")
    s.sample()
    s.sample()
    summary = s.summary()
    assert summary is not None and summary["gpus"][0]["peak_gts"] == 16.0 and summary["degraded"] is False


def test_too_few_readings_give_no_verdict(tmp_path: Path) -> None:
    summary = sampled(machine(tmp_path, "2.5"), times=2)
    assert summary["samples"] == 2 and summary["degraded"] is False


def test_no_sysfs_means_not_checked(tmp_path: Path) -> None:
    s = gpulink.Sampler(tmp_path / "nothing")
    with s.busy():
        pass
    s.close()
    assert s.summary() is None


def test_the_thread_samples_only_during_a_request(tmp_path: Path) -> None:
    s = gpulink.Sampler(machine(tmp_path, "2.5"), settle_s=0.0, step_s=0.01)
    with s.busy():
        import time

        deadline = time.monotonic() + 2
        while s.samples < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    taken = s.samples
    assert taken >= 3
    s.close()
    assert s.samples <= taken + 1


def test_is_this_host() -> None:
    assert gpulink.is_this_host("http://127.0.0.1:8080/v1")
    assert gpulink.is_this_host("http://localhost:11434/v1")
    assert not gpulink.is_this_host("http://192.0.2.1:11434/v1")  # TEST-NET-1: nobody's interface
    assert not gpulink.is_this_host("")


def test_enforced(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(gpulink.ENV_OFF, raising=False)
    assert gpulink.enforced()
    monkeypatch.setenv(gpulink.ENV_OFF, "1")
    assert not gpulink.enforced()
