"""The emulated AWS account (the `moto` service) for grading: its tools, a snapshot of its resources, and
what changed since.

The grader has no AWS client of its own: it runs the toolbox image's `aws`, `terraform` and a boto3 script
(images/toolbox/aws_snapshot.py), with the environment from services/moto/service.yaml. So it reads the
account through the same tools as the model, in a separate container.

`stick task start` saves the snapshot to baseline/moto.json right after setup; the `aws_unchanged` check
compares it with the account at grading time.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from llm_on_a_stick import services
from llm_on_a_stick.env.containerlab import ContainerlabError
from llm_on_a_stick.runner import toolbox

SERVICE = "moto"
SNAPSHOT_SCRIPT = "/usr/local/lib/stick/aws_snapshot.py"  # in the toolbox image

Snapshot = dict[str, dict[str, dict[str, Any]]]  # kind (ec2/vpcs...) -> resource id -> resource


_image_checked = False


class AwsStateError(RuntimeError):
    pass


def tool_env() -> dict[str, str]:
    """AWS_ENDPOINT_URL, credentials and region for the emulator."""
    return dict(services.load(SERVICE).env)


def run(
    command: str, workspace: Path | None = None, cwd: str = "", timeout_s: int = 120
) -> subprocess.CompletedProcess[str]:
    """Run a command (aws ..., terraform ...) in a throwaway toolbox container against the emulator."""
    global _image_checked
    try:
        if not _image_checked:  # `stick task start` and `stick grade` may be the first to need the image
            toolbox.ensure_image(log=None)
            _image_checked = True
        return toolbox.run_once(command, tool_env(), workspace, cwd, timeout_s)
    except (toolbox.ToolboxError, ContainerlabError) as exc:
        raise AwsStateError(str(exc)) from exc


def unreachable(output: str) -> bool:
    """The tool could not reach the emulator at all (as opposed to AWS answering with an error)."""
    return any(
        text in output
        for text in ("Could not connect to the endpoint URL", "connection refused", "Unable to find image")
    )


def snapshot() -> Snapshot:
    res = run(f"python3 {SNAPSHOT_SCRIPT}")
    if res.returncode != 0:
        tail = " | ".join((res.stderr or res.stdout).strip().splitlines()[-2:])
        raise AwsStateError(f"cannot read the AWS account (exit {res.returncode}): {tail[:400]}")
    data: Snapshot = json.loads(res.stdout)
    return data


def _allowed(kind: str, obj: dict[str, Any], allow: list[str]) -> bool:
    """`allow` entries are a kind ("ec2/volumes": any of them) or kind:label ("ec2/security-groups:web")."""
    return kind in allow or f"{kind}:{obj.get('label')}" in allow


def diff(
    before: Snapshot,
    after: Snapshot,
    allow_new: list[str],
    allow_changed: list[str],
    allow_deleted: list[str],
) -> list[str]:
    """Changes from `before` to `after` that none of the allow lists covers."""
    problems: list[str] = []
    for kind, old in before.items():
        new = after.get(kind, {})
        for rid, obj in old.items():
            if rid not in new:
                if not _allowed(kind, obj, allow_deleted):
                    problems.append(f"{kind}: deleted {obj.get('label', rid)}")
            elif new[rid] != obj and not _allowed(kind, obj, allow_changed):
                fields = sorted(k for k in set(obj) | set(new[rid]) if obj.get(k) != new[rid].get(k))
                problems.append(f"{kind}: changed {obj.get('label', rid)} ({', '.join(fields)})")
        problems += [
            f"{kind}: added {obj.get('label', rid)}"
            for rid, obj in new.items()
            if rid not in old and not _allowed(kind, obj, allow_new)
        ]
    return problems
