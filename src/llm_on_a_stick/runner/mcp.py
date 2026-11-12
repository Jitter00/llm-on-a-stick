"""MCP servers as the model's tools (the mcp section): no shell, only what the servers offer.

One container per server and attempt, from the stick-mcp image (images/mcp: the upstream servers, pinned),
on the host network, spoken to over stdio. Which servers a task gets is its `tools.mcp` list; how each one
is started is the `mcp:` block of that service's service.yaml.

The MCP SDK is asynchronous and the runner's loop is not: `McpHub` keeps an event loop in a background thread,
with one long-lived task per server that owns its session (the SDK's scopes must be entered and left in the
same task) and serves calls from a queue.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import copy
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from llm_on_a_stick.env import containerlab
from llm_on_a_stick.runner.models import ToolDef
from llm_on_a_stick.runner.toolbox import shorten
from llm_on_a_stick.services.spec import McpServer

IMAGE = os.environ.get("STICK_MCP_IMAGE", "stick-mcp:dev")
# The `stick.mcp.version` label of images/mcp/Dockerfile.
MCP_IMAGE_VERSION = "2"

# "<server>__<tool>": what the model calls. Both model APIs limit tool names to these characters and 64 long.
SEPARATOR = "__"
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
START_TIMEOUT_S = 90
LONG_RESULT = "Ask for less: use the tool's filters, fields and limit."

# JSON Schema keywords the model APIs don't all accept in a tool's parameters, or that only cost tokens.
DROPPED_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "definitions",
        "title",
        "format",
        "pattern",
        "default",
        "examples",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "additionalProperties",
    }
)
# Keywords whose value is a map of names to schemas: the names are not keywords.
SCHEMA_MAPS = frozenset({"properties"})


class McpError(RuntimeError):
    pass


def ensure_image(log: object = print) -> None:
    """Build stick-mcp:dev if it is missing or older than this code expects (see MCP_IMAGE_VERSION)."""
    label = '{{ index .Config.Labels "stick.mcp.version" }}'
    res = subprocess.run(
        ["docker", "image", "inspect", "--format", label, IMAGE], capture_output=True, text=True, check=False
    )
    found = res.returncode == 0
    if found and (IMAGE != "stick-mcp:dev" or res.stdout.strip() == MCP_IMAGE_VERSION):
        return  # your own image (STICK_MCP_IMAGE) is used as it is
    if not found and IMAGE != "stick-mcp:dev":
        raise McpError(f"MCP image {IMAGE} not found")
    if callable(log):
        why = "its servers changed" if found else "once"
        log(f"building the MCP server image ({why}; a few minutes: it installs six servers) ...")
    containerlab.build_image("mcp")


# --------------------------------------------------------------------------- tool schemas


def _resolve(node: Any, defs: dict[str, Any], seen: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_resolve(n, defs, seen) for n in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name in seen or name not in defs:
            return {}  # recursive or unknown: anything goes
        rest = {k: v for k, v in node.items() if k != "$ref"}
        return _resolve({**copy.deepcopy(defs[name]), **rest}, defs, (*seen, name))
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: _resolve(sub, defs, seen) for name, sub in value.items()}
        elif key not in DROPPED_KEYWORDS:
            out[key] = _resolve(value, defs, seen)
    for union in ("anyOf", "oneOf"):
        options = out.get(union)
        if isinstance(options, list):
            real = [o for o in options if not (isinstance(o, dict) and o.get("type") == "null")]
            if len(real) == 1 and isinstance(real[0], dict):  # "X or null" is how servers say "optional X"
                del out[union]
                out = {**real[0], **out}
            else:
                out[union] = real
    return out


def sanitize_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """A tool's input schema in the subset every model API takes, the same for every model: references
    inlined, "X or null" reduced to X, and keywords that some servers reject (or that only cost tokens)
    removed. Always an object schema."""
    schema = schema or {}
    defs = {**(schema.get("definitions") or {}), **(schema.get("$defs") or {})}
    out = _resolve(schema, defs, ())
    if not isinstance(out, dict) or out.get("type") != "object":
        out = {"type": "object", "properties": {}}
    out.setdefault("properties", {})
    return dict(out)


def tool_name(server: str, tool: str) -> str:
    return f"{server}{SEPARATOR}{tool}"


def tool_defs(server: str, tools: list[dict[str, Any]], allow: list[str]) -> list[ToolDef]:
    """What the model is shown of one server's tools (`tools`: name, description, input_schema): only the
    allowed ones (all, if the list is empty), in the server's order, named <server>__<tool>."""
    missing = sorted(set(allow) - {str(t["name"]) for t in tools})
    if missing:
        raise McpError(f"MCP server {server} has no tool named {', '.join(missing)}: fix its allow list")
    out: list[ToolDef] = []
    for t in tools:
        if allow and t["name"] not in allow:
            continue
        name = tool_name(server, str(t["name"]))
        if not TOOL_NAME.match(name):
            raise McpError(f"MCP tool name {name!r} is not one a model can call")
        description = str(t.get("description") or "").strip()
        out.append(ToolDef(name, description, sanitize_schema(t.get("input_schema"))))
    return out


def schema_chars(defs: list[ToolDef]) -> int:
    """How much the tool list costs in the context: names, descriptions and schemas."""
    return sum(len(d.name) + len(d.description) + len(json.dumps(d.parameters)) for d in defs)


def flatten(content: list[Any]) -> str:
    """A tool result as text: its text parts; anything else (images, embedded resources) is only named."""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else f"[{getattr(block, 'type', 'content')} omitted]")
    return "\n".join(parts)


# --------------------------------------------------------------------------- the hub


@dataclass
class CallResult:
    output: str  # possibly shortened
    output_chars: int  # length before shortening
    is_error: bool
    timed_out: bool
    seconds: float

    @property
    def truncated(self) -> bool:
        return len(self.output) < self.output_chars


Launcher = Callable[[str, McpServer], list[str]]


class McpHub:
    """The MCP servers of one attempt. `servers` maps the name the model sees (the service's) to how the
    server is started; `launcher` returns the command line of one (tests replace it)."""

    def __init__(
        self,
        servers: dict[str, McpServer],
        run_id: str,
        log_dir: Path,
        max_output: int = 4000,
        launcher: Launcher | None = None,
    ) -> None:
        self.servers = servers
        self.run_id = run_id
        self.log_dir = log_dir
        self.max_output = max_output
        self.launcher = launcher or self._docker
        self.defs: list[ToolDef] = []
        self.info: dict[str, dict[str, Any]] = {}  # per server: version and tools, for the transcript
        self._routes: dict[str, tuple[str, str]] = {}  # model's tool name -> (server, server's tool name)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._queues: dict[str, asyncio.Queue[Any]] = {}
        self._tasks: list[concurrent.futures.Future[None]] = []

    def _container(self, name: str) -> str:
        return f"stick-mcp-{name}-{self.run_id}".lower()[:120]

    def _docker(self, name: str, server: McpServer) -> list[str]:
        env = [arg for key, value in server.env.items() for arg in ("-e", f"{key}={value}")]
        return [
            "docker", "run", "-i", "--rm", "--name", self._container(name), "--network", "host",
            "--label", "stick-mcp=1", *env, IMAGE, server.server,
        ]  # fmt: skip

    def __enter__(self) -> McpHub:
        try:
            self.start()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="stick-mcp", daemon=True)
        self._thread.start()
        for name, server in self.servers.items():
            ready: asyncio.Future[list[dict[str, Any]]] = asyncio.run_coroutine_threadsafe(
                self._new_future(), self._loop
            ).result()
            self._tasks.append(asyncio.run_coroutine_threadsafe(self._serve(name, server, ready), self._loop))
            try:
                tools = asyncio.run_coroutine_threadsafe(self._wait(ready), self._loop).result(
                    START_TIMEOUT_S
                )
            except Exception as exc:
                raise McpError(
                    f"MCP server {name} did not start: {exc or type(exc).__name__} "
                    f"(its log: {self.log_dir / f'mcp-{name}.log'})"
                ) from exc
            defs = tool_defs(name, tools, server.allow)
            for d in defs:
                self._routes[d.name] = (name, d.name.split(SEPARATOR, 1)[1])
            self.defs += defs
            self.info[name] = {
                "server": server.server,
                "version": server.version,
                "tools": [d.name for d in defs],
                "tools_hidden": len(tools) - len(defs),
            }

    async def _new_future(self) -> asyncio.Future[Any]:
        return asyncio.get_running_loop().create_future()

    async def _wait(self, future: asyncio.Future[Any]) -> Any:
        return await future

    async def _serve(self, name: str, server: McpServer, ready: asyncio.Future[Any]) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        argv = self.launcher(name, server)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._queues[name] = queue
        params = StdioServerParameters(command=argv[0], args=argv[1:], env=dict(os.environ))
        try:
            with (self.log_dir / f"mcp-{name}.log").open("w", encoding="utf-8") as errlog:
                async with (
                    stdio_client(params, errlog=errlog) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    listed = await session.list_tools()
                    ready.set_result(
                        [
                            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                            for t in listed.tools
                        ]
                    )
                    while (item := await queue.get()) is not None:
                        tool, arguments, timeout_s, done = item
                        try:
                            done.set_result(
                                await session.call_tool(tool, arguments, read_timeout_seconds=timeout_s)
                            )
                        except Exception as exc:  # a timeout, a protocol error, a dead server
                            done.set_exception(exc)
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)

    def stop(self) -> None:
        loop = self._loop
        if loop is not None:
            for queue in self._queues.values():
                loop.call_soon_threadsafe(queue.put_nowait, None)
            for task in self._tasks:
                with contextlib.suppress(Exception):
                    task.result(10)
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(10)
            self._loop = None
        if self.launcher == self._docker:  # whatever happened above, no server outlives the attempt
            for name in self.servers:
                subprocess.run(
                    ["docker", "rm", "-f", self._container(name)], capture_output=True, check=False
                )

    # ------------------------------------------------------------------ calls

    def knows(self, name: str) -> bool:
        return name in self._routes

    def call(self, name: str, arguments: dict[str, Any], timeout_s: int = 60) -> CallResult:
        """Call one tool by the name the model uses. Errors (the tool's own, a timeout, a server that died)
        come back as the result's text: the model reads them like any other tool output."""
        server, tool = self._routes[name]
        loop = self._loop
        if loop is None:
            raise McpError("the MCP servers are not running")
        t0 = time.monotonic()
        timed_out = False
        try:
            done = asyncio.run_coroutine_threadsafe(self._new_future(), loop).result()
            loop.call_soon_threadsafe(self._queues[server].put_nowait, (tool, arguments, timeout_s, done))
            res = asyncio.run_coroutine_threadsafe(self._wait(done), loop).result(timeout_s + 15)
            text, is_error = flatten(list(res.content)), bool(res.is_error)
        except Exception as exc:
            timed_out = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
            what = f"timed out after {timeout_s}s" if timed_out else f"{type(exc).__name__}: {exc}"
            text, is_error = f"error: the call to {name} failed: {what}", True
        return CallResult(
            output=shorten(text, self.max_output, LONG_RESULT),
            output_chars=len(text),
            is_error=is_error,
            timed_out=timed_out,
            seconds=round(time.monotonic() - t0, 3),
        )
