"""`stick` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from llm_on_a_stick import __version__, doctor, paths, services, tasks
from llm_on_a_stick.env import containerlab
from llm_on_a_stick.grading import grade as grade_mod
from llm_on_a_stick.grading import run as run_mod
from llm_on_a_stick.grading import validate as validate_mod
from llm_on_a_stick.grading.labstate import DockerLabState, LabStateError
from llm_on_a_stick.grading.template import TemplateError
from llm_on_a_stick.services import lifecycle
from llm_on_a_stick.services.seed import RestError

app = typer.Typer(
    name="stick",
    help="llm-on-a-stick: one eval harness, many LLMs. Start poking.",
    no_args_is_help=True,
    add_completion=False,
)
env_app = typer.Typer(help="Bring the lab up, down, or inspect it.", no_args_is_help=True)
image_app = typer.Typer(help="Build the images we ship as source (e.g. stick-frr).", no_args_is_help=True)
task_app = typer.Typer(help="Work with benchmark tasks.", no_args_is_help=True)
svc_app = typer.Typer(
    help="Tool-stack services (NetBox, ...): up, down, status, reset.", no_args_is_help=True
)
app.add_typer(env_app, name="env")
app.add_typer(image_app, name="image")
app.add_typer(task_app, name="task")
app.add_typer(svc_app, name="svc")

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


TasksDirOpt = Annotated[
    list[Path] | None,
    typer.Option(
        "--tasks-dir", help="Extra folder(s) with your own tasks (built-in sections are always searched)."
    ),
]
RunsDirOpt = Annotated[Path, typer.Option("--runs-dir", help="Where run folders are created.")]


def _task_roots(extra: list[Path] | None) -> list[Path]:
    return [paths.sections_dir(), *(extra or [])]


@task_app.command("list")
def task_list(tasks_dir: TasksDirOpt = None) -> None:
    """List the available tasks."""
    table = Table("task", "section", "tier", "title")
    for path in tasks.discover(_task_roots(tasks_dir)):
        try:
            t = tasks.load_task(path)
        except tasks.TaskError as exc:
            err.print(f"[red]{exc}[/]")
            continue
        table.add_row(t.id, t.section, t.tier, t.title)
    console.print(table)


@task_app.command("start")
def task_start(
    task: Annotated[str, typer.Argument(help="Task id, or a path to a task folder.")],
    tasks_dir: TasksDirOpt = None,
    runs_dir: RunsDirOpt = Path("runs"),
    seed: Annotated[int | None, typer.Option(help="Seed for canary values (for reproducible runs).")] = None,
) -> None:
    """Prepare an attempt: workspace, canary values, setup, baseline. Prints the prompt for the agent."""
    try:
        t = tasks.find_task(task, _task_roots(tasks_dir))
        lab = DockerLabState(t.topology)
        problems = validate_mod.check_requirements(t, lab)
        if problems:
            raise run_mod.RunError(f"{t.id}: " + "; ".join(problems))
        info = run_mod.start(t, runs_dir, lab, seed=seed)
    except (tasks.TaskError, run_mod.RunError, LabStateError, TemplateError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[bold]Run[/]: {info.run_dir}", soft_wrap=True)
    console.print(f"[bold]Workspace[/] (the agent writes its files here): {info.workspace}", soft_wrap=True)
    console.print("[bold]Prompt for the agent[/]:")
    console.print(info.prompt, markup=False, highlight=False, soft_wrap=True)
    console.print(f"\nWhen the agent is done: [bold]uv run stick grade {info.run_dir}[/]")


@task_app.command("validate")
def task_validate(
    task_refs: Annotated[
        list[str] | None, typer.Argument(help="Task ids or paths (default: all tasks).")
    ] = None,
    tasks_dir: TasksDirOpt = None,
    runs_dir: RunsDirOpt = Path("runs/validate"),
    seed: Annotated[int | None, typer.Option(help="Seed for canary values.")] = None,
) -> None:
    """Prove tasks are sound: the oracle must pass and doing nothing must fail. Needs the lab running."""
    roots = _task_roots(tasks_dir)
    try:
        selected = (
            [tasks.find_task(r, roots) for r in task_refs]
            if task_refs
            else [tasks.load_task(p) for p in tasks.discover(roots)]
        )
    except tasks.TaskError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    table = Table("task", "oracle", "do nothing", "verdict")
    failures = 0
    for t in selected:
        console.print(f"validating {t.id} ...", highlight=False)
        v = validate_mod.validate(t, DockerLabState(t.topology), runs_dir, seed)
        failures += not v.ok
        verdict = "[green]ok[/]" if v.ok else f"[red]{v.problem}[/]"
        table.add_row(t.id, v.oracle_outcome or "-", v.noop_outcome or "-", verdict)
    console.print(table)
    console.print(f"{len(selected) - failures} of {len(selected)} task(s) valid")
    raise typer.Exit(1 if failures else 0)


@app.command("grade")
def grade_cmd(
    run_dir: Annotated[Path | None, typer.Argument(help="Run folder (default: the latest one).")] = None,
    runs_dir: RunsDirOpt = Path("runs"),
    as_json: Annotated[bool, typer.Option("--json", help="Print result.json instead of a table.")] = False,
) -> None:
    """Grade an attempt against the live lab and write result.json. Exit: 0 pass, 1 fail/partial, 2 error."""
    try:
        target = run_dir or run_mod.latest(runs_dir)
        result = grade_mod.grade(target)
    except (run_mod.RunError, tasks.TaskError, LabStateError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    if as_json:
        console.print_json(result.model_dump_json())
    else:
        style = {"pass": "green", "partial": "yellow", "fail": "red", "error": "magenta"}
        table = Table("check", "status", "details")
        for c in result.checks:
            hints = f" [dim]({', '.join(c.hints)})[/]" if c.hints else ""
            table.add_row(c.name, f"[{style[c.status]}]{c.status}[/]", c.message + hints)
        console.print(table)
        console.print(
            f"[bold]{result.task_id}[/]: [{style[result.outcome]}]{result.outcome}[/] "
            f"(score {result.score:.2f}) -> {target / 'result.json'}"
        )
    raise typer.Exit({"pass": 0, "partial": 1, "fail": 1, "error": 2}[result.outcome])


ServiceNames = Annotated[
    list[str], typer.Argument(help="Service names, e.g. netbox. Started one after another.")
]


def _load_services(names: list[str]) -> list[services.ServiceSpec]:
    try:
        return [services.load(n) for n in names]
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


@svc_app.command("list")
def svc_list() -> None:
    """List the services this version knows about."""
    table = Table("service", "description")
    for name in services.available():
        table.add_row(name, services.load(name).description)
    console.print(table)


@svc_app.command("up")
def svc_up(
    names: ServiceNames,
    seed: Annotated[bool, typer.Option(help="Load baseline seed data.")] = True,
) -> None:
    """Start services one at a time, seed them and take a baseline snapshot."""
    for spec in _load_services(names):
        console.print(f"[bold]{spec.name}[/]")
        try:
            lifecycle.up(spec, seed=seed, log=lambda m: console.print(f"  {m}"))
        except (lifecycle.ServiceError, RestError) as exc:
            err.print(f"[red]{spec.name}: {exc}[/]")
            raise typer.Exit(1) from exc
        for label, url in spec.endpoints.items():
            console.print(f"  {label}: {url}", soft_wrap=True)
        for key, value in spec.credentials.items():
            console.print(f"  {key}: {value}", soft_wrap=True)


@svc_app.command("down")
def svc_down(
    names: ServiceNames,
    volumes: Annotated[bool, typer.Option(help="Also delete data volumes (including the snapshot).")] = False,
) -> None:
    """Stop services."""
    for spec in _load_services(names):
        try:
            lifecycle.down(spec, volumes=volumes)
        except lifecycle.ServiceError as exc:
            err.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        console.print(f"[green]stopped[/] {spec.name}")


@svc_app.command("status")
def svc_status(
    names: Annotated[list[str] | None, typer.Argument(help="Services (default: all).")] = None,
) -> None:
    """Show container state and whether each service answers its health check."""
    table = Table("service", "container", "state", "health", "api")
    for spec in _load_services(names or services.available()):
        try:
            rows = lifecycle.status(spec)
        except lifecycle.ServiceError:
            rows = []
        api = "[green]ok[/]" if rows and lifecycle.healthy(spec) else "[dim]-[/]"
        if not rows:
            table.add_row(spec.name, "-", "[dim]not running[/]", "", api)
        for i, r in enumerate(rows):
            table.add_row(
                spec.name if i == 0 else "", r["service"], r["state"], r["health"], api if i == 0 else ""
            )
    console.print(table)


@svc_app.command("reset")
def svc_reset(names: ServiceNames) -> None:
    """Restore services to their baseline snapshot (what `svc up` seeded)."""
    for spec in _load_services(names):
        console.print(f"[bold]{spec.name}[/]")
        try:
            lifecycle.restore_snapshot(spec, log=lambda m: console.print(f"  {m}"))
        except lifecycle.ServiceError as exc:
            err.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        console.print(f"[green]reset[/] {spec.name}")


@svc_app.command("snapshot")
def svc_snapshot(names: ServiceNames) -> None:
    """Replace the baseline snapshot with the service's current state."""
    for spec in _load_services(names):
        try:
            lifecycle.take_snapshot(spec)
        except lifecycle.ServiceError as exc:
            err.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        console.print(f"[green]snapshot taken[/] {spec.name}")
