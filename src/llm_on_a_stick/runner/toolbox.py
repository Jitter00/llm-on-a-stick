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
from pathlib import Path, PurePosixPath
from types import TracebackType

from llm_on_a_stick.env import containerlab

IMAGE = os.environ.get("STICK_TOOLBOX_IMAGE", "stick-toolbox:dev")
# The `stick.toolbox.version` label of images/toolbox/Dockerfile. 2: adds aws, boto3 and terraform;
# 3: adds snmpget and snmpwalk.
TOOLBOX_VERSION = "4"


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


LONG_OUTPUT = "Save long output to a file and read it with grep, head or sed -n"


def shorten(text: str, limit: int, advice: str = LONG_OUTPUT) -> str:
    """Keep the head and the tail; say how much was left out (so the model knows) and what to do about it."""
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.75), int(limit * 0.25)
    omitted = len(text) - head - tail
    return f"{text[:head]}\n[... {omitted} characters omitted. {advice} ...]\n{text[-tail:]}"


def ensure_image(log: object = print) -> None:
    """Build stick-toolbox:dev if it is missing or older than this code expects (see TOOLBOX_VERSION)."""
    label = '{{ index .Config.Labels "stick.toolbox.version" }}'
    res = subprocess.run(
        ["docker", "image", "inspect", "--format", label, IMAGE], capture_output=True, text=True, check=False
    )
    found = res.returncode == 0
    if found and (IMAGE != "stick-toolbox:dev" or res.stdout.strip() == TOOLBOX_VERSION):
        return  # your own image (STICK_TOOLBOX_IMAGE) is used as it is
    if not found and IMAGE != "stick-toolbox:dev":
        raise ToolboxError(f"toolbox image {IMAGE} not found")
    if callable(log):
        why = "its tools changed" if found else "once"
        log(f"building the toolbox image ({why}; a few minutes: it downloads the AWS CLI and Terraform) ...")
    containerlab.build_image("toolbox")


# Where the run's workspace appears inside the toolbox: short, so models needn't copy a long host path.
WORKDIR = "/work"


def _env_args(env: dict[str, str] | None) -> list[str]:
    return [arg for key, value in (env or {}).items() for arg in ("-e", f"{key}={value}")]


def run_once(
    command: str,
    env: dict[str, str] | None = None,
    workspace: Path | None = None,
    cwd: str = "",
    timeout_s: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run one bash command in a throwaway toolbox container, as the calling user: how the grader uses the
    image's tools (aws, terraform) without needing them on the host. `workspace` is mounted at /work, and
    `cwd` is a directory under it."""
    argv = ["docker", "run", "--rm", "--network", "host", "-e", "HOME=/tmp", *_env_args(env)]
    if hasattr(os, "getuid"):  # files it writes in the workspace stay the user's
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    if workspace is not None:
        argv += ["-v", f"{workspace.resolve()}:{WORKDIR}", "-w", str(PurePosixPath(WORKDIR) / cwd)]
    argv += [IMAGE, "timeout", "-k", "5", str(timeout_s), "bash", "-c", command]
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s + 30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ToolboxError(f"cannot run `{command[:80]}` in the toolbox: {exc}") from exc


class Toolbox:
    def __init__(
        self, workspace: Path, name: str, max_output: int = 4000, env: dict[str, str] | None = None
    ) -> None:
        self.workspace = workspace.resolve()
        self.name = name
        self.max_output = max_output
        self.env = env or {}  # e.g. AWS_ENDPOINT_URL, from the services the task requires

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
                *_env_args(self.env),
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
