"""The toolbox container: the only place a model's commands run.

One container per run, on the host network (it reaches the lab's management IPs and service ports like an
engineer on the host), with the run's workspace mounted at /work: the path the prompt names, short so
it's easy to copy.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from llm_on_a_stick.env import containerlab

IMAGE = os.environ.get("STICK_TOOLBOX_IMAGE", "stick-toolbox:dev")


class ToolboxError(RuntimeError):
    pass


@dataclass
class CommandResult:
    exit_code: int
    output: str  # stdout and stderr interleaved, possibly shortened
    output_chars: int  # length before shortening
    timed_out: bool
    seconds: float

    @property
    def truncated(self) -> bool:
        return len(self.output) < self.output_chars


def shorten(text: str, limit: int) -> str:
    """Keep the head and the tail; say how much was left out (so the model knows)."""
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.75), int(limit * 0.25)
    omitted = len(text) - head - tail
    return (
        f"{text[:head]}\n[... {omitted} characters omitted: write long output to a file and read it in"
        f" parts ...]\n{text[-tail:]}"
    )


def ensure_image(log: object = print) -> None:
    res = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    if res.returncode == 0:
        return
    if IMAGE != "stick-toolbox:dev":
        raise ToolboxError(f"toolbox image {IMAGE} not found")
    if callable(log):
        log("building the toolbox image (once, about a minute) ...")
    containerlab.build_image("toolbox")


# Where the run's workspace appears inside the toolbox: short, so models needn't copy a long host path.
WORKDIR = "/work"


class Toolbox:
    def __init__(self, workspace: Path, name: str, max_output: int = 16000) -> None:
        self.workspace = workspace.resolve()
        self.name = name
        self.max_output = max_output

    def __enter__(self) -> Toolbox:
        self.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()

    def start(self) -> None:
        ws = str(self.workspace)
        res = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.name,
                "--network",
                "host",
                "--label",
                "stick-toolbox=1",
                "-v",
                f"{ws}:{WORKDIR}",
                "-w",
                WORKDIR,
                IMAGE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise ToolboxError(f"cannot start the toolbox container: {res.stderr.strip()}")

    def exec(self, command: str, timeout_s: int = 60) -> CommandResult:
        t0 = time.monotonic()
        argv = ["docker", "exec", self.name, "timeout", "-k", "5", str(timeout_s), "bash", "-c", command]
        try:
            res = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_s + 20,
            )
            code, raw = res.returncode, res.stdout
        except subprocess.TimeoutExpired as exc:
            code, raw = 124, exc.stdout or b""
        text = raw.decode("utf-8", "replace")
        return CommandResult(
            exit_code=code,
            output=shorten(text, self.max_output),
            output_chars=len(text),
            timed_out=code == 124,
            seconds=round(time.monotonic() - t0, 3),
        )

    def stop(self) -> None:
        # Files the model wrote are owned by root in the container: hand them back to the user.
        if hasattr(os, "getuid"):
            subprocess.run(
                [
                    "docker",
                    "exec",
                    self.name,
                    "chown",
                    "-R",
                    f"{os.getuid()}:{os.getgid()}",
                    WORKDIR,
                ],
                capture_output=True,
                check=False,
            )
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, check=False)
