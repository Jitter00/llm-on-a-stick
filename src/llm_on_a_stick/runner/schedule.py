"""Which lab instance each model of a `stick vs` gets, and running them at the same time.

Two models can work at once only when each has a lab of its own and they don't compete for the machine: at
most one of them is local. `plan()` decides; `run_children()` starts one `stick run` per model, each on
its instance.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from llm_on_a_stick import lab


class ScheduleError(Exception):
    pass


@dataclass(frozen=True)
class Plan:
    """`instances` holds one lab instance per model when they run at the same time, and is None when they
    run one after the other on the current instance; `reason` says why, for the user."""

    instances: tuple[int, ...] | None
    reason: str

    @property
    def parallel(self) -> bool:
        return self.instances is not None


def plan(
    local: Sequence[bool],
    here: int,
    is_free: Callable[[int], bool],
    need_mb: Callable[[int], int],
    usable_mb: int,
    sequential: bool = False,
) -> Plan:
    """One instance per model, or one after the other.

    `local[i]` says whether model i runs on this machine; `here` is the current instance, which the first
    model keeps; `is_free(n)` whether nothing holds instance n; `need_mb(n)` the RAM that what the tasks
    need would still take on instance n (0 when it is running already); `usable_mb` the RAM to spend.
    """
    if sum(local) > 1:
        raise ScheduleError("more than one local model: they never run at the same time")
    if sequential:
        return Plan(None, "--sequential")
    if len(local) < 2:
        return Plan(None, "one model")
    if not is_free(here):
        return Plan(None, f"lab instance {here} is in use")  # the caller's own claim reports it
    chosen = [here]
    budget = usable_mb - need_mb(here)
    for _ in local[1:]:
        free = [n for n in range(lab.MAX_INSTANCES) if n not in chosen and is_free(n)]
        if not free:
            return Plan(None, "no other lab instance is free")
        n = free[0]
        budget -= need_mb(n)
        chosen.append(n)
    if budget < 0:
        short = -budget
        return Plan(None, f"a lab per model needs about {short} MiB more RAM than is usable")
    return Plan(tuple(chosen), "a lab instance per model")


def local_model_lock_path() -> Path:
    return lab.state_dir(0).parent.parent / "local-model.lock"


@contextlib.contextmanager
def local_model_lock(model: str) -> Iterator[None]:
    """Held while a local model is being tested: a second run with a local model, from any terminal,
    folder or lab instance, is refused. They would share the GPU and RAM."""
    import fcntl  # not on Windows, where there is no lab either

    path = local_model_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.seek(0)
            holder = fh.read().strip() or "a local model"
            raise ScheduleError(
                f"another stick run is testing {holder} on this machine: local models run one after "
                f"another, never together (they share the GPU and RAM). Wait for it, then run {model}."
            ) from exc
        fh.seek(0)
        fh.truncate()
        fh.write(model)
        fh.flush()
        try:
            yield
        finally:
            fh.seek(0)
            fh.truncate()
            fcntl.flock(fh, fcntl.LOCK_UN)


def child_argv(instance: int, run_args: Sequence[str]) -> list[str]:
    return [sys.executable, "-m", "llm_on_a_stick", "--instance", str(instance), "run", *run_args]


def run_children(
    jobs: Sequence[tuple[str, list[str]]],
    log: Callable[[str, str], None],
    columns: int | None = None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> list[int]:
    """Run every job (label, argv) at the same time; each output line goes to `log(label, line)`.
    Returns the exit codes in the order of `jobs`. Ctrl+C stops them all. `columns` is the width the
    children format their output for (they don't see the terminal)."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if columns:
        env["COLUMNS"] = str(columns)
    env.pop(lab.INSTANCE_VAR, None)  # each child gets its instance from its --instance option
    procs = [
        popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        for _, argv in jobs
    ]

    def pump(label: str, proc: subprocess.Popen[str]) -> None:
        for line in proc.stdout or []:
            log(label, line.rstrip("\n"))

    threads = [
        threading.Thread(target=pump, args=(label, proc), daemon=True)
        for (label, _), proc in zip(jobs, procs, strict=True)
    ]
    for t in threads:
        t.start()
    try:
        codes = [proc.wait() for proc in procs]
    except KeyboardInterrupt:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            proc.wait()
        raise
    for t in threads:
        t.join(timeout=5)
    return codes
