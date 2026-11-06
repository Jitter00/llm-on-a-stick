"""`stick` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from llm_on_a_stick import __version__, doctor, paths, tasks
from llm_on_a_stick.env import containerlab

app = typer.Typer(
    name="stick",
    help="llm-on-a-stick: one eval harness, many LLMs. Start poking.",
    no_args_is_help=True,
    add_completion=False,
)
env_app = typer.Typer(help="Bring the lab up, down, or inspect it.", no_args_is_help=True)
image_app = typer.Typer(help="Build the images we ship as source (e.g. stick-frr).", no_args_is_help=True)
task_app = typer.Typer(help="Work with benchmark tasks.", no_args_is_help=True)
app.add_typer(env_app, name="env")
app.add_typer(image_app, name="image")
app.add_typer(task_app, name="task")

console = Console()
err = Console(stderr=True)

_STATUS_STYLE = {"ok": "[green]ok[/]", "warn": "[yellow]warn[/]", "fail": "[red]fail[/]"}

TopologyOpt = Annotated[
    str, typer.Option("--topology", "-t", help="Built-in topology name or .clab.yml path.")
]


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


@app.command("doctor")
def doctor_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    reserve_mb: Annotated[
        int, typer.Option(help="RAM to keep free for a local model that isn't loaded yet (MiB).")
    ] = 0,
) -> None:
    """Check this machine and report what it can run."""
    report = doctor.run_doctor(reserve_mb=reserve_mb)
    if as_json:
        console.print_json(json.dumps(report.to_dict()))
        raise typer.Exit(0 if report.ok else 1)

    h = report.host
    console.print(
        f"[bold]Host[/]: {h.os_family}/{h.arch}, {h.cpu_count} CPUs, "
        f"{h.ram_available_mb} / {h.ram_total_mb} MiB RAM available, {h.disk_free_gb} GB disk free"
    )
    checks = Table("check", "status", "detail", box=None, pad_edge=False)
    for c in report.checks:
        checks.add_row(c.name, _STATUS_STYLE[c.status], c.detail)
    console.print(checks)

    b = report.budget
    console.print(
        f"[bold]RAM budget[/]: {b.usable_mb} MiB usable (margin {b.margin_mb}, reserved {b.reserved_mb}); "
        f"base lab ~{b.base_lab_mb} MiB (measured), all services ~{b.all_services_mb} MiB "
        "[dim](services are estimates until each one is brought up)[/]"
    )
    for s in report.model_servers:
        models = ", ".join(s.loaded_models) or "no models loaded"
        console.print(
            f"[bold]Model server[/]: {s.name} at {s.url}: {models} (RAM {s.ram_mb}, VRAM {s.vram_mb} MiB)"
        )
    for g in report.gpus:
        console.print(f"[bold]GPU[/]: {g.name}, {g.vram_mb} MiB")
    caps = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in report.capabilities.items())
    console.print(f"[bold]Can run[/]: {caps}")
    raise typer.Exit(0 if report.ok else 1)


@env_app.command("up")
def env_up(
    topology: TopologyOpt = "base",
    reconfigure: Annotated[bool, typer.Option(help="Redeploy from scratch if the lab exists.")] = False,
) -> None:
    """Deploy a lab with containerlab."""
    try:
        topo = containerlab.deploy(topology, reconfigure=reconfigure)
    except (containerlab.ContainerlabError, FileNotFoundError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]deployed[/] {topo}")


@env_app.command("down")
def env_down(topology: TopologyOpt = "base") -> None:
    """Destroy a lab (and clean up its lab directory)."""
    try:
        containerlab.destroy(topology)
    except (containerlab.ContainerlabError, FileNotFoundError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print("[green]destroyed[/]")


@env_app.command("status")
def env_status(topology: TopologyOpt = "base") -> None:
    """Show the lab's nodes."""
    try:
        nodes = containerlab.inspect(topology)
    except (containerlab.ContainerlabError, FileNotFoundError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    table = Table("node", "kind", "state", "mgmt ipv4", "image")
    for n in nodes:
        table.add_row(n.name, n.kind, n.state, n.mgmt_ipv4, n.image)
    console.print(table)


@image_app.command("build")
def image_build(
    name: Annotated[str, typer.Argument(help="Image directory under images/, e.g. frr.")] = "frr",
    tag: Annotated[str | None, typer.Option(help="Override the image tag.")] = None,
) -> None:
    """Build an image locally (default: stick-frr:dev)."""
    try:
        built = containerlab.build_image(name, tag)
    except (containerlab.ContainerlabError, FileNotFoundError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]built[/] {built}")


@task_app.command("lint")
def task_lint(
    roots: Annotated[
        list[Path] | None, typer.Argument(help="Task dirs or task.yaml files (default: built-in sections).")
    ] = None,
) -> None:
    """Validate task.yaml files against the task schema."""
    found, errors = tasks.lint(roots or [paths.sections_dir()])
    for e in errors:
        err.print(f"[red]{e.path}[/]: {e.message}")
    console.print(f"{len(found)} task file(s) checked, {len(errors)} error(s)")
    raise typer.Exit(1 if errors else 0)
