"""`stick` command-line interface."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import typer
from rich.console import Console
from rich.table import Table

from llm_on_a_stick import __version__, doctor, dotenv, paths, services, tasks
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
    help="llm-on-a-stick: one eval harness, many LLMs. Start poking.\n\n"
    "Settings (server addresses, API keys) can live in a .env file in the current folder: see .env.example.",
    no_args_is_help=True,
    add_completion=False,
)
env_app = typer.Typer(
    help="Bring the lab up, inspect it, or stop everything (lab and services).", no_args_is_help=True
)
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
_OUTCOME_STYLE = {"pass": "green", "partial": "yellow", "fail": "red", "error": "magenta"}

TopologyOpt = Annotated[
    str, typer.Option("--topology", "-t", help="Built-in topology name or .clab.yml path.")
]
ENV_FILE = ".env"


@app.callback()
def _main() -> None:
    env_file = Path(ENV_FILE)
    added = dotenv.load(env_file)
    if added:  # say so: a .env in an unfamiliar folder must not redirect API calls unnoticed
        err.print(f"[dim]{env_file.resolve()}: using {', '.join(added)}[/]", highlight=False, soft_wrap=True)


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
    """Stop everything: the tool-stack services that are running, then the lab.

    Services keep their data (`stick svc down <name> --volumes` deletes it), so the next start is quick.
    """
    try:
        for name in services.available():  # first: they are attached to the lab's network
            spec = services.load(name)
            if lifecycle.status(spec):
                lifecycle.down(spec)
                console.print(f"[green]stopped[/] {spec.name}")
        if containerlab.inspect(topology):
            containerlab.destroy(topology)
            console.print("[green]destroyed[/] the lab")
        else:
            console.print("[dim]the lab wasn't running[/]")
    except (containerlab.ContainerlabError, lifecycle.ServiceError, FileNotFoundError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


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
        style = _OUTCOME_STYLE
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


# --------------------------------------------------------------------------- runner


def _select_tasks(
    refs: list[str] | None, sections: list[str] | None, all_: bool, roots: list[Path]
) -> list[tasks.Task]:
    if refs:
        return [tasks.find_task(r, roots) for r in refs]
    if not (sections or all_):
        raise tasks.TaskError("say which tasks: task ids, --section <name> or --all")
    found = [tasks.load_task(p) for p in tasks.discover(roots)]
    known = sorted({t.section for t in found})
    for name in sections or []:
        if name in known:
            continue
        if any(t.id == name for t in found):  # a task id given as a section
            raise tasks.TaskError(
                f"{name!r} is a task, not a section: give it without --section (`stick run {name} ...`)"
            )
        raise tasks.TaskError(f"no section {name!r}; sections: {', '.join(known)}")
    return [t for t in found if all_ or t.section in (sections or [])]


ModelOpt = Annotated[
    list[str],
    typer.Option(
        "--model",
        "-m",
        help="provider/model, e.g. ollama/qwen3:14b, strata/<model>, anthropic/claude-sonnet-5-5. "
        "Repeatable.",
    ),
]
SectionOpt = Annotated[list[str] | None, typer.Option("--section", "-s", help="Run every task in a section.")]
AllOpt = Annotated[bool, typer.Option("--all", help="Run every task.")]
RepeatOpt = Annotated[int, typer.Option(min=1, help="Attempts per model and task.")]
BaseUrlOpt = Annotated[
    str | None,
    typer.Option(
        help="Server address for OpenAI-compatible models, e.g. http://127.0.0.1:9000/v1. It applies to "
        "every model given; with models from different providers set STICK_<PROVIDER>_BASE_URL instead."
    ),
]
MaxTurnsOpt = Annotated[int | None, typer.Option(help="Override the task's turn limit.")]
TimeoutOpt = Annotated[
    int | None,
    typer.Option(
        "--timeout", help="Safety time limit per attempt (s); default 3600. The real limit is the turns."
    ),
]
CmdTimeoutOpt = Annotated[int, typer.Option(help="Seconds before one command is stopped.")]
TemperatureOpt = Annotated[
    float | None,
    typer.Option(
        help="Sampling temperature for every model (OpenAI-compatible servers). Default: the model's "
        "recommended settings from data/sampling.yaml, else 0."
    ),
]
EffortOpt = Annotated[str | None, typer.Option(help="Anthropic effort: low, medium, high, xhigh, max.")]
ThinkingOpt = Annotated[
    bool,
    typer.Option(
        "--thinking/--no-thinking",
        help="Anthropic models: let the model think before it answers. Off by default, so models are "
        "compared at their plainest; a model that can't turn thinking off runs with it on, and the "
        "report says so. No effect on other providers.",
    ),
]
MinFreeRamOpt = Annotated[
    int,
    typer.Option(
        help="MiB of RAM to keep free for the system; attempts pause, then stop, below it (0 = off)."
    ),
]
SeedOpt = Annotated[int | None, typer.Option(help="Seed for canary values.")]
NoReportOpt = Annotated[
    bool, typer.Option("--no-report", help="Don't write report.html and report.json into the runs folder.")
]


@app.command("run")
def run_cmd(
    task_refs: Annotated[list[str] | None, typer.Argument(help="Task ids or paths.")] = None,
    model: ModelOpt = [],  # noqa: B006 (typer reads the default; it is never mutated)
    section: SectionOpt = None,
    all_: AllOpt = False,
    repeat: RepeatOpt = 1,
    base_url: BaseUrlOpt = None,
    max_turns: MaxTurnsOpt = None,
    timeout_s: TimeoutOpt = None,
    cmd_timeout: CmdTimeoutOpt = 60,
    temperature: TemperatureOpt = None,
    effort: EffortOpt = None,
    thinking: ThinkingOpt = False,
    min_free_ram: MinFreeRamOpt = 2048,
    tasks_dir: TasksDirOpt = None,
    runs_dir: RunsDirOpt = Path("runs"),
    seed: SeedOpt = None,
    no_report: NoReportOpt = False,
) -> None:
    """Let models attempt tasks in the lab, grade each attempt and compare.

    Starts what the tasks need and isn't running yet (the lab, and services such as NetBox) and leaves it
    running afterwards.

    Ends with a summary table and, in the runs folder, report.html: scores, where each model struggled and
    every attempt's checks and transcript.
    """
    if not model:
        err.print("[red]give at least one --model, e.g. --model ollama/qwen3:14b[/]")
        raise typer.Exit(2)
    _run_models(
        model, task_refs, section, all_, repeat, base_url, max_turns, timeout_s, cmd_timeout, temperature,
        effort, thinking, min_free_ram, tasks_dir, runs_dir, seed, no_report,
    )  # fmt: skip


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", model.split("/", 1)[-1]).strip("-")


@app.command("vs")
def vs_cmd(
    model_a: Annotated[str, typer.Argument(help="First model, provider/model.")],
    model_b: Annotated[str, typer.Argument(help="Second model, provider/model.")],
    task_refs: Annotated[list[str] | None, typer.Argument(help="Task ids or paths.")] = None,
    section: SectionOpt = None,
    all_: AllOpt = False,
    repeat: RepeatOpt = 1,
    base_url: BaseUrlOpt = None,
    max_turns: MaxTurnsOpt = None,
    timeout_s: TimeoutOpt = None,
    cmd_timeout: CmdTimeoutOpt = 60,
    temperature: TemperatureOpt = None,
    effort: EffortOpt = None,
    thinking: ThinkingOpt = False,
    min_free_ram: MinFreeRamOpt = 2048,
    tasks_dir: TasksDirOpt = None,
    runs_dir: Annotated[
        Path | None,
        typer.Option(help="Where the attempts and the report go (default: runs/vs-<a>-vs-<b>-<time>)."),
    ] = None,
    seed: SeedOpt = None,
) -> None:
    """Two models on the same tasks, side by side: runs both, then writes the versus report.

    The models run one after the other, the first one's whole batch before the second (they share the one
    lab). To compare runs you already have: `stick report <folder> <folder> --html`.
    """
    if model_a == model_b:
        err.print("[red]give two different models[/]")
        raise typer.Exit(2)
    if runs_dir is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        runs_dir = Path("runs") / f"vs-{_slug(model_a)}-vs-{_slug(model_b)}-{stamp}"
    _run_models(
        [model_a, model_b], task_refs, section, all_, repeat, base_url, max_turns, timeout_s, cmd_timeout,
        temperature, effort, thinking, min_free_ram, tasks_dir, runs_dir, seed, False,
    )  # fmt: skip


def _run_models(
    model: list[str],
    task_refs: list[str] | None,
    section: list[str] | None,
    all_: bool,
    repeat: int,
    base_url: str | None,
    max_turns: int | None,
    timeout_s: int | None,
    cmd_timeout: int,
    temperature: float | None,
    effort: str | None,
    thinking: bool,
    min_free_ram: int,
    tasks_dir: list[Path] | None,
    runs_dir: Path,
    seed: int | None,
    no_report: bool,
) -> None:
    """`stick run` and `stick vs`: every model's whole batch, one model after the other."""
    from llm_on_a_stick.runner import loop, models, report, toolbox

    try:
        selected = _select_tasks(task_refs, section, all_, _task_roots(tasks_dir))
        clients = [models.make_client(m, base_url, temperature, effort, thinking=thinking) for m in model]
        local = [c.spec.spec for c in clients if c.spec.endpoint.local and c.spec.provider != "script"]
        if len(local) > 1:
            raise models.ModelError(
                f"{', '.join(local)} are local models: run them one after another, never together "
                "(they compete for the same GPU and RAM). One `stick run` per local model, stopping the "
                "first model's server before the next; then `stick report` compares them."
            )
        for c in clients:
            console.print(
                f"checking {c.spec.spec} at {c.spec.base_url or c.spec.provider} ...", highlight=False
            )
            c.check()
            if c.sampling:
                shown = ", ".join(f"{k} {v}" for k, v in c.sampling.items() if v is not None) or "defaults"
                console.print(f"  sampling: {shown} ({c.sampling_source})", highlight=False)
        toolbox.ensure_image(console.print)
    except (tasks.TaskError, models.ModelError, toolbox.ToolboxError, containerlab.ContainerlabError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    if not selected:
        err.print("[red]no tasks matched[/]")
        raise typer.Exit(2)
    _bring_up(selected)

    free = loop.available_ram_mb()
    if min_free_ram and free < min_free_ram:
        err.print(
            f"[red]only {free} MiB RAM available, below --min-free-ram {min_free_ram}. "
            "Close something (or stop other model servers) first.[/]"
        )
        raise typer.Exit(2)
    settings = loop.Settings(
        max_turns=max_turns,
        timeout_s=timeout_s,
        cmd_timeout_s=cmd_timeout,
        seed=seed,
        min_free_ram_mb=min_free_ram,
    )
    style = _OUTCOME_STYLE
    done: list[Path] = []
    errors = 0
    for c in clients:  # model by model: one model's whole batch before the next
        for t in selected:
            lab = DockerLabState(t.topology)
            for i in range(repeat):
                attempt = f" (attempt {i + 1}/{repeat})" if repeat > 1 else ""
                console.print(f"[bold]{t.id}[/] with {c.spec.spec}{attempt}", highlight=False)
                try:
                    info, result, m = loop.run_task(t, c, lab, runs_dir, settings, log=console.print)
                except (run_mod.RunError, LabStateError, TemplateError, toolbox.ToolboxError) as exc:
                    err.print(f"  [red]{exc}[/]")
                    errors += 1
                    continue
                done.append(info.run_dir)
                hints = f" [dim]({', '.join(result.failure_hints)})[/]" if result.failure_hints else ""
                console.print(
                    f"  [{style[result.outcome]}]{result.outcome}[/] score {result.score:.2f}, "
                    f"{m.turns} turns, "
                    f"{m.tokens_in + m.tokens_out} tokens, {m.wall_s:.0f}s, stop: {m.stop_reason}{hints}",
                    highlight=False,
                )
                console.print(f"  [dim]{info.run_dir}[/]", soft_wrap=True, highlight=False)
    rows = report.collect(done)
    if rows:
        console.print()
        _print_report(rows)
        if not no_report:  # this run's attempts only: the folder may hold older runs of other models
            name = _report_name(model, task_refs, section, all_)
            _write_html(done, runs_dir / name, title=None, task=None)
    raise typer.Exit(1 if errors else 0)


def _bring_up(selected: list[tasks.Task]) -> None:
    """Start the lab(s) and services the tasks need, unless they are running already."""
    topologies = sorted({t.topology for t in selected if t.requires.get("devices")})  # some need no lab
    names = sorted({str(s) for t in selected for s in t.requires.get("services", []) or []})
    stop: list[str] = []
    try:
        for topology in topologies:
            if any(n.state == "running" for n in containerlab.inspect(topology)):
                continue
            console.print(f"starting the lab ({topology}), it isn't running ...", highlight=False)
            containerlab.deploy(topology)
            stop.append(topology)
        stopped = [spec for spec in _load_services(names) if not lifecycle.healthy(spec)]
        for spec in stopped:
            console.print(f"starting {spec.name}, it isn't running ...", highlight=False)
            lifecycle.up(spec, log=lambda m: console.print(f"  {m}"))
        stop += [spec.name for spec in stopped]
    except (containerlab.ContainerlabError, FileNotFoundError, lifecycle.ServiceError, RestError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    if stop:
        console.print("[dim]left running afterwards; to stop everything: stick env down[/]", highlight=False)


def _print_report(rows: list[Any]) -> None:
    from llm_on_a_stick.runner import report

    table = Table(
        "model", "sampling", "runs", "passed", "mean score", "tokens", "cost", "mean time",
        "most common problems",
    )  # fmt: skip
    for s in report.summarise(rows):
        cost = "?" if s.cost_usd is None else f"${s.cost_usd:.4f}"
        table.add_row(s.model, s.sampling or "-", str(s.runs), str(s.passed), f"{s.mean_score:.2f}",
                      str(s.tokens), cost, f"{s.mean_wall_s}s", ", ".join(s.common_hints) or "-")  # fmt: skip
    console.print(table)


def _write_html(targets: list[Path], out: Path, title: str | None, task: str | None) -> bool:
    from llm_on_a_stick.runner import html as html_mod

    data = html_mod.write(targets, out, title or "", task)
    if data is None:
        return False
    kind = "versus report" if data["versus"] else "report"
    # A file:// address: most terminals make it clickable (Ctrl+click, or Cmd+click on a Mac).
    console.print(f"\n[bold]Open the {kind} in your browser:[/]", highlight=False)
    console.print(f"  {_file_url(out)}", soft_wrap=True, highlight=False, markup=False)
    console.print(
        f"  [dim]same numbers as data: {out.with_suffix('.json')}[/]", soft_wrap=True, highlight=False
    )
    return True


def _file_url(path: Path) -> str:
    """An address a browser opens. Under WSL the browser runs on Windows, which reaches the Linux files
    through \\\\wsl.localhost\\<distribution>, so the address names that instead of a plain Linux path."""
    url = path.resolve().as_uri()  # file:///home/...
    distro = os.environ.get("WSL_DISTRO_NAME")
    if distro:
        return f"file://wsl.localhost/{quote(distro)}{url.removeprefix('file://')}"
    return url


def _report_name(model: list[str], task_refs: list[str] | None, section: list[str] | None, all_: bool) -> str:
    """`report-<model(s)>-<what was run>-<time>.html`: tells the reports in one folder apart."""
    if all_:
        what = "all"
    elif section:
        what = "+".join(section)
    else:
        refs = [Path(r).name for r in task_refs or []]
        what = refs[0] if len(refs) == 1 else f"{len(refs)}-tasks"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"report-{'-vs-'.join(_slug(m) for m in model)}-{_slug(what)}-{stamp}.html"


@app.command("report")
def report_cmd(
    paths_: Annotated[
        list[Path] | None, typer.Argument(help="Run folders, or folders of runs (default: runs/).")
    ] = None,
    fmt: Annotated[str, typer.Option("--format", "-f", help="table, md, json or html.")] = "table",
    html: Annotated[
        bool, typer.Option("--html", help="Write the HTML report (same as --format html).")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="Where the HTML report goes (default: report.html in the folder given, or here when "
            "several are given). report.json is written next to it.",
        ),
    ] = None,
    title: Annotated[str | None, typer.Option(help="Heading of the HTML report.")] = None,
    task: Annotated[str | None, typer.Option(help="Only this task.")] = None,
) -> None:
    """Compare model runs: pass rate, score, tokens, cost, time and the most common problems.

    With --html: one self-contained page with the scores, where each model struggled, and every attempt's
    checks and transcript. Two models in the data are shown side by side.
    """
    from llm_on_a_stick.runner import report

    targets = paths_ or [Path("runs")]
    if html or fmt == "html":
        target = out or (targets[0] if len(targets) == 1 else Path()) / "report.html"
        if not _write_html(targets, target, title, task):
            err.print("[yellow]no model runs found; start some with `stick run`[/]")
            raise typer.Exit(1)
        return
    rows = report.collect(targets)
    if task:
        rows = [r for r in rows if r.task_id == task]
    if not rows:
        err.print("[yellow]no model runs found; start some with `stick run`[/]")
        raise typer.Exit(1)
    if fmt == "json":
        console.print(report.to_json(rows), markup=False, highlight=False, soft_wrap=True)
    elif fmt == "md":
        console.print(report.to_markdown(rows), markup=False, highlight=False, soft_wrap=True)
    else:
        _print_report(rows)
        style = _OUTCOME_STYLE
        table = Table("task", "model", "outcome", "score", "turns", "tokens in/out", "time", "problems")
        for r in rows:
            table.add_row(
                r.task_id,
                r.model,
                f"[{style.get(r.outcome, 'white')}]{r.outcome}[/]",
                f"{r.score:.2f}",
                str(r.turns),
                f"{r.tokens_in}/{r.tokens_out}",
                f"{r.wall_s:.0f}s",
                ", ".join(r.hints) or "-",
            )
        console.print(table)


@app.command("hints")
def hints_cmd(
    paths_: Annotated[
        list[Path] | None, typer.Argument(help="Run folders, or folders of runs (default: runs/).")
    ] = None,
) -> None:
    """Show the transcript hints of past attempts (read-only: result.json is not changed)."""
    from llm_on_a_stick.grading.transcript import transcript_hints

    found: list[Path] = []
    for p in paths_ or [Path("runs")]:
        found += (
            [p]
            if (p / "transcript.jsonl").exists()
            else sorted(q.parent for q in p.glob("*/transcript.jsonl"))
        )
    if not found:
        err.print("[yellow]no attempts with a transcript.jsonl found[/]")
        raise typer.Exit(1)
    table = Table("model", "run", "outcome", "recorded hints", "transcript hints")
    for run_dir in found:
        model, recorded, outcome = "-", "-", "?"
        if (run_dir / "result.json").exists():
            res = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            outcome, recorded = res.get("outcome", "?"), ", ".join(res.get("failure_hints", [])) or "-"
            model = (res.get("metrics") or {}).get("model") or "-"
        hints = ", ".join(transcript_hints(run_dir)) or "-"
        table.add_row(model, run_dir.name, outcome, recorded, hints)
    console.print(table)
