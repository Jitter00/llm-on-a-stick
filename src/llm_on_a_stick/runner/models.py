"""Model access: one small interface, three backends.

- `openai`-style chat completions (stdlib HTTP): Ollama, LM Studio, vLLM, llama.cpp, Strata, OpenAI,
  OpenRouter,
  and any other OpenAI-compatible server (`openai-compat/<model>` + a base URL).
- `anthropic`: the official Anthropic SDK (Messages API).
- `script`: replays a YAML list of commands. No model involved; for testing the harness and the tasks.

A model is named `provider/model`, e.g. `ollama/qwen3:14b`, `strata/deepseek-v4.1-flash`,
`anthropic/claude-sonnet-5-5`, `openai-compat/my-model` (with --base-url).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import cache
from http.client import HTTPResponse
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol

import yaml

from llm_on_a_stick.grading.template import render


class ModelError(RuntimeError):
    """The model server failed or refused (not the model getting a task wrong)."""


@dataclass(frozen=True)
class Endpoint:
    kind: str  # openai | anthropic | script
    base_url: str = ""
    api_key_env: str | None = None  # environment variable holding the API key (never stored)
    local: bool = True  # local servers have no per-token cost


# Built-in providers. Base URLs can be overridden with --base-url or STICK_<PROVIDER>_BASE_URL.
ENDPOINTS: dict[str, Endpoint] = {
    "ollama": Endpoint("openai", "http://127.0.0.1:11434/v1"),
    "lmstudio": Endpoint("openai", "http://127.0.0.1:1234/v1"),
    "vllm": Endpoint("openai", "http://127.0.0.1:8000/v1"),
    "llamacpp": Endpoint("openai", "http://127.0.0.1:8080/v1"),
    "strata": Endpoint("openai", "http://127.0.0.1:8080/v1"),
    "openai-compat": Endpoint("openai", "", "STICK_API_KEY"),
    "openai": Endpoint("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", local=False),
    "openrouter": Endpoint("openai", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", local=False),
    "anthropic": Endpoint("anthropic", "", "ANTHROPIC_API_KEY", local=False),
    "script": Endpoint("script"),
}


# --------------------------------------------------------------------------- neutral types


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None  # None when the model sent arguments that aren't a JSON object
    raw_arguments: str = ""


@dataclass
class ToolResult:
    call_id: str
    output: str
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int = 0  # everything the model read this turn (prompt incl. history)
    output_tokens: int = 0


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str  # as reported by the server (end_turn, tool_use, stop, refusal, ...)
    seconds: float = 0.0
    reasoning: str = ""  # visible reasoning, if the server returns it
    usage_estimated: bool = False  # the reply was stopped early, so the server never reported usage

    @property
    def cut_off(self) -> bool:
        """The reply hit the output-token cap (OpenAI: `length`, Anthropic: `max_tokens`) or was stopped
        early because it was repeating itself (`repetition`)."""
        return self.stop_reason in CUT_OFF


CUT_OFF = frozenset({"length", "max_tokens", "repetition"})


def repeating(text: str, tail: int = 100, times: int = 5) -> bool:
    """The text ends in a loop: its last `tail` characters occur at least `times` times.

    A reply stuck in a loop is periodic, so any stretch of its end recurs once per period, with or
    without line breaks. Normal prose or a long config doesn't repeat a 100-character stretch 5 times.
    """
    text = text.rstrip()
    if len(text) < tail * times:
        return False
    return text.count(text[-tail:]) >= times


def context_full(turn: Turn, context_window: int | None) -> bool:
    """A cut-off reply that stopped because the conversation filled the context window (not the output cap):
    prompt + reply reach the window. The model can't continue in this conversation."""
    if not context_window or turn.stop_reason != "length":
        return False
    return turn.usage.input_tokens + turn.usage.output_tokens >= context_window * 0.99


LOOP_CHECK_EVERY = 2000  # characters of streamed reply between two loop checks


class Session(Protocol):
    def step(self) -> Turn: ...
    def add_results(self, results: list[ToolResult]) -> None: ...
    def add_message(self, text: str) -> None: ...  # a user message from the runner (e.g. the nudge)


@dataclass
class ModelSpec:
    spec: str  # as given, e.g. "ollama/qwen3:14b"
    provider: str
    model: str
    endpoint: Endpoint
    base_url: str


def parse_spec(spec: str, base_url: str | None = None) -> ModelSpec:
    provider, sep, model = spec.partition("/")
    if not sep or not model:
        raise ModelError(f"model {spec!r} must look like provider/model, e.g. ollama/qwen3:14b")
    if provider not in ENDPOINTS:
        raise ModelError(f"unknown provider {provider!r}; known: {', '.join(sorted(ENDPOINTS))}")
    endpoint = ENDPOINTS[provider]
    env_url = os.environ.get(f"STICK_{provider.upper().replace('-', '_')}_BASE_URL")
    default = endpoint.base_url
    if provider == "ollama" and os.environ.get("OLLAMA_HOST"):  # same server Ollama's own CLI talks to
        from llm_on_a_stick.doctor import ollama_base

        default = ollama_base() + "/v1"
    url = (base_url or env_url or default).rstrip("/")
    if endpoint.kind == "openai" and not url:
        raise ModelError(f"{provider} needs a server address: --base-url http://host:port/v1")
    return ModelSpec(spec, provider, model, endpoint, url)


def api_key(m: ModelSpec) -> str | None:
    env = m.endpoint.api_key_env
    key = os.environ.get(env) if env else None
    if env and not key and not m.endpoint.local:
        raise ModelError(f"{m.provider} needs an API key in the environment variable {env}")
    return key


class Client(Protocol):
    spec: ModelSpec
    context_window: int | None  # tokens the server allows, when it says (filled in by check())
    sampling: dict[str, Any]  # sampling settings sent with every request (recorded in the metrics)
    sampling_source: str  # where they came from: data/sampling.yaml: <entry> | default | --temperature

    def check(self) -> None: ...
    def new_session(
        self, system: str, prompt: str, tools: list[ToolDef], variables: dict[str, Any]
    ) -> Session: ...


# Most a single reply may write (thinking included), the same for every model. Normal turns here use 100-2,000
# tokens and a whole config is under 3,000; the cap bounds the time lost to a loop the runner can't see.
MAX_OUTPUT_TOKENS = 8000

DEFAULT_TEMPERATURE = 0.0  # for models data/sampling.yaml doesn't list


@cache
def _sampling_entries() -> list[dict[str, Any]]:
    text = files("llm_on_a_stick").joinpath("data/sampling.yaml").read_text(encoding="utf-8")
    entries = (yaml.safe_load(text) or {}).get("models") or []
    for e in entries:
        if not isinstance(e.get("match"), list) or not isinstance(e.get("temperature"), (int, float)):
            raise ModelError(f"data/sampling.yaml: entry {e.get('name')!r} needs `match:` and `temperature:`")
    return entries


def recommended_sampling(model: str) -> tuple[dict[str, float], str]:
    """Sampling settings for a model name (the part after provider/) from data/sampling.yaml, and where
    they came from. Models the file doesn't list get temperature 0."""
    name = model.lower()
    for e in _sampling_entries():
        if any(fnmatchcase(name, str(p).lower()) for p in e["match"]):
            values = {"temperature": float(e["temperature"])}
            if isinstance(e.get("top_p"), (int, float)):
                values["top_p"] = float(e["top_p"])
            return values, f"data/sampling.yaml: {e.get('name') or e['match'][0]}"
    return {"temperature": DEFAULT_TEMPERATURE}, "default"


def make_client(
    spec: str,
    base_url: str | None = None,
    temperature: float | None = None,
    effort: str | None = None,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> Client:
    """`temperature` given (e.g. --temperature): sent as is, nothing else. Not given: data/sampling.yaml's
    values for the model, else temperature 0."""
    m = parse_spec(spec, base_url)
    if m.endpoint.kind == "openai":
        if temperature is not None:
            sampling, source = {"temperature": temperature}, "--temperature"
        else:
            sampling, source = recommended_sampling(m.model)
        return OpenAIClient(m, sampling, source, max_output_tokens)
    if m.endpoint.kind == "anthropic":
        return AnthropicClient(m, effort, max_output_tokens)
    return ScriptClient(m)


# --------------------------------------------------------------------------- OpenAI-compatible


def _open(method: str, url: str, body: Any, headers: dict[str, str], timeout: float) -> HTTPResponse:
    """Send a request, retrying rate limits, server errors and connection errors (3 attempts)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310 (URL comes from the user's own config)
        url, data=data, method=method, headers={"Content-Type": "application/json", **headers}
    )
    attempts = 3
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout)  # type: ignore[no-any-return]  # noqa: S310
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:800]
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise ModelError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise ModelError(f"cannot reach {url}: {exc}") from exc
    raise ModelError(f"no response from {url}")  # pragma: no cover


def _http_json(method: str, url: str, body: Any, headers: dict[str, str], timeout: float) -> Any:
    with _open(method, url, body, headers, timeout) as resp:
        try:
            return json.loads(resp.read().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ModelError(f"{url} did not return JSON: {exc}") from exc


def _http_stream(url: str, body: Any, headers: dict[str, str], timeout: float) -> Generator[dict[str, Any]]:
    """POST and yield the server-sent events (`data: {...}` lines) of a streamed reply.

    Closing the generator closes the connection, which makes the server stop generating."""
    with _open("POST", url, body, headers, timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
            try:
                event = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ModelError(f"{url} sent a malformed stream event: {payload[:200]}") from exc
            if isinstance(event, dict) and event.get("error"):
                raise ModelError(f"{url}: {str(event['error'])[:500]}")
            if isinstance(event, dict):
                yield event


class OpenAIClient:
    def __init__(
        self,
        spec: ModelSpec,
        sampling: dict[str, float],
        sampling_source: str = "",
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> None:
        self.spec = spec
        self.max_output_tokens = max_output_tokens
        self.timeout = float(os.environ.get("STICK_MODEL_TIMEOUT_S", "600"))  # local models can be slow
        self.context_window: int | None = None
        # Sent with every request; anything not in it (top_k, min_p...) stays at the server's defaults.
        self.sampling: dict[str, Any] = dict(sampling)
        self.sampling_source = sampling_source

    def headers(self) -> dict[str, str]:
        key = api_key(self.spec)
        return {"Authorization": f"Bearer {key}"} if key else {}

    def check(self) -> None:
        """The server answers and serves this model."""
        data = _http_json("GET", f"{self.spec.base_url}/models", None, self.headers(), 10)
        ids = [str(m.get("id")) for m in (data.get("data") or [])] if isinstance(data, dict) else []
        if ids and self.spec.model not in ids:
            shown = ", ".join(ids[:15]) + (" ..." if len(ids) > 15 else "")
            raise ModelError(f"{self.spec.base_url} doesn't serve {self.spec.model!r}; it has: {shown}")
        entries = (data.get("data") or []) if isinstance(data, dict) else []
        for entry in entries:
            n_ctx = (entry.get("meta") or {}).get("n_ctx")  # llama.cpp-based servers (Strata, llama.cpp)
            if entry.get("id") == self.spec.model and isinstance(n_ctx, int):
                self.context_window = n_ctx
        if self.spec.provider == "ollama":
            self.context_window = self._ollama_context()

    def _ollama_context(self) -> int | None:
        """Load the model now (so a model that can't load fails before any task starts), then read its
        runtime context window from /api/ps."""
        root = self.spec.base_url.removesuffix("/v1")
        try:
            _http_json("POST", f"{root}/api/generate", {"model": self.spec.model}, {}, self.timeout)
        except ModelError as exc:
            hint = " (GPU memory full? Stop other model servers first)" if "out of memory" in str(exc) else ""
            raise ModelError(f"Ollama cannot load {self.spec.model}{hint}: {exc}") from exc
        try:
            ps = _http_json("GET", f"{root}/api/ps", None, {}, 10)
        except ModelError:
            return None
        for m in (ps.get("models") or []) if isinstance(ps, dict) else []:
            if self.spec.model in (m.get("name"), m.get("model")):
                value = m.get("context_length")
                return int(value) if isinstance(value, int) else None
        return None

    def new_session(
        self, system: str, prompt: str, tools: list[ToolDef], variables: dict[str, Any]
    ) -> OpenAISession:
        return OpenAISession(self, system, prompt, tools)


class OpenAISession:
    def __init__(self, client: OpenAIClient, system: str, prompt: str, tools: list[ToolDef]) -> None:
        self.client = client
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        self.tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
            }
            for t in tools
        ]
        self._n = 0
        self._last_read = 0  # prompt tokens of the last reply, for estimates

    def step(self) -> Turn:
        """One streamed reply. The stream is checked for loops as it arrives: a reply that starts repeating
        itself is stopped there (stop reason `repetition`) instead of running on to the output cap."""
        c = self.client
        body: dict[str, Any] = {
            "model": c.spec.model,
            "messages": self.messages,
            "tools": self.tools,
            "tool_choice": "auto",
            "max_tokens": c.max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        body.update(c.sampling)
        content: list[str] = []
        reasoning: list[str] = []
        slots: dict[int, dict[str, Any]] = {}  # tool calls, assembled from their deltas
        finish, usage = "", dict[str, Any]()
        chars, next_check = 0, LOOP_CHECK_EVERY
        t0 = time.monotonic()
        events = _http_stream(f"{c.spec.base_url}/chat/completions", body, c.headers(), c.timeout)
        try:
            for event in events:
                usage = event.get("usage") or usage
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        content.append(delta["content"])
                        chars += len(delta["content"])
                    thought = delta.get("reasoning_content") or delta.get("reasoning")
                    if thought:
                        reasoning.append(thought)
                        chars += len(thought)
                    for i, tc in enumerate(delta.get("tool_calls") or []):
                        slot = slots.setdefault(
                            int(tc.get("index", i)),
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["function"]["name"] = slot["function"]["name"] or fn.get("name") or ""
                        args = fn.get("arguments")
                        if isinstance(args, dict):  # some servers send an object, not a string
                            slot["function"]["arguments"] = json.dumps(args)
                        elif args:
                            slot["function"]["arguments"] += args
                    finish = choice.get("finish_reason") or finish
                if chars >= next_check:
                    next_check = chars + LOOP_CHECK_EVERY
                    if repeating("".join(reasoning) + "\n" + "".join(content)):
                        finish = "repetition"
                        break
        except (OSError, TimeoutError) as exc:
            raise ModelError(f"the stream from {c.spec.base_url} broke off: {exc}") from exc
        finally:
            events.close()  # stops the server generating if we broke off
        seconds = time.monotonic() - t0

        text = "".join(content)
        stopped = finish == "repetition"
        raw_calls = [] if stopped else [slots[i] for i in sorted(slots)]  # stopped: calls are partial
        calls = []
        for raw in raw_calls:
            args_raw = raw["function"]["arguments"]
            try:
                parsed = json.loads(args_raw or "{}")
                args = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                args = None
            if not raw["id"]:  # some local servers omit ids; the next request needs them
                self._n += 1
                raw["id"] = f"call_{self._n}"
            calls.append(ToolCall(raw["id"], raw["function"]["name"], args, args_raw))
        # Keep the assistant message (with ids filled in) for the next request. A loop isn't sent back.
        kept: dict[str, Any] = {"role": "assistant", "content": "" if stopped else text}
        if raw_calls:
            kept["tool_calls"] = raw_calls
        self.messages.append(kept)
        if usage:
            read, wrote = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            self._last_read = read
        else:  # stopped early: no usage from the server, so estimate (about 4 characters per token)
            prompt_chars = len(json.dumps(self.messages[:-1])) + len(json.dumps(self.tools))
            read, wrote = max(self._last_read, prompt_chars // 4), chars // 4
        return Turn(
            text=text,
            tool_calls=calls,
            usage=Usage(read, wrote),
            stop_reason=finish,
            seconds=seconds,
            reasoning="".join(reasoning),
            usage_estimated=not usage,
        )

    def add_results(self, results: list[ToolResult]) -> None:
        for r in results:
            self.messages.append({"role": "tool", "tool_call_id": r.call_id, "content": r.output})

    def add_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})


# --------------------------------------------------------------------------- Anthropic


class AnthropicClient:
    def __init__(self, spec: ModelSpec, effort: str | None, max_output_tokens: int) -> None:
        import anthropic  # imported lazily: only needed for Claude models

        self.spec = spec
        self.context_window: int | None = None
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.sampling: dict[str, Any] = {"effort": effort}  # Claude models take no temperature
        self.sampling_source = "--effort" if effort else "default"
        kwargs: dict[str, Any] = {"max_retries": 3}
        if spec.base_url:
            kwargs["base_url"] = spec.base_url
        # Credentials: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile
        # (the SDK resolves them).
        self.sdk = anthropic
        try:
            self.client = anthropic.Anthropic(**kwargs)
        except anthropic.AnthropicError as exc:
            raise ModelError(f"no Anthropic credentials: set ANTHROPIC_API_KEY ({exc})") from exc

    def check(self) -> None:
        try:
            self.client.models.retrieve(self.spec.model)
        except self.sdk.NotFoundError as exc:
            raise ModelError(f"Anthropic has no model {self.spec.model!r}") from exc
        except self.sdk.AuthenticationError as exc:
            raise ModelError("the Anthropic API key was rejected") from exc
        except self.sdk.APIError as exc:
            raise ModelError(f"Anthropic API: {exc}") from exc

    def new_session(
        self, system: str, prompt: str, tools: list[ToolDef], variables: dict[str, Any]
    ) -> AnthropicSession:
        return AnthropicSession(self, system, prompt, tools)


class AnthropicSession:
    def __init__(self, client: AnthropicClient, system: str, prompt: str, tools: list[ToolDef]) -> None:
        self.c = client
        self.system = system
        self.tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
        ]
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    def step(self) -> Turn:
        kwargs: dict[str, Any] = {
            "model": self.c.spec.model,
            "max_tokens": self.c.max_output_tokens,
            "system": self.system,
            "tools": self.tools,
            "messages": self.messages,
        }
        if self.c.effort:
            kwargs["output_config"] = {"effort": self.c.effort}
        t0 = time.monotonic()
        try:
            resp = self.c.client.messages.create(**kwargs)
        except self.c.sdk.APIError as exc:
            raise ModelError(f"Anthropic API: {exc}") from exc
        seconds = time.monotonic() - t0
        # Append the content blocks unchanged (thinking blocks must be passed back as received).
        self.messages.append({"role": "assistant", "content": resp.content})
        text, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else None
                calls.append(ToolCall(block.id, block.name, args, json.dumps(block.input)))
        u = resp.usage
        read = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        read += getattr(u, "cache_creation_input_tokens", 0) or 0
        return Turn("\n".join(text), calls, Usage(read, u.output_tokens or 0), str(resp.stop_reason), seconds)

    def add_results(self, results: list[ToolResult]) -> None:
        blocks = [
            {"type": "tool_result", "tool_use_id": r.call_id, "content": r.output, "is_error": r.is_error}
            for r in results
        ]
        self.messages.append({"role": "user", "content": blocks})  # all results in one message

    def add_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})


# --------------------------------------------------------------------------- script (no model)


class ScriptClient:
    """`script/<file.yaml>`: run fixed commands, e.g. a task's reference steps. Proves the harness works.

    The YAML has `commands:` (strings, may use {{ workspace }}, {{ nodes.frr1.mgmt_ip }}, {{ canaries.x }})
    and an optional `final:` message.
    """

    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.context_window: int | None = None
        self.sampling: dict[str, Any] = {}
        self.sampling_source = ""
        self.path = Path(spec.model)

    def check(self) -> None:
        if not self.path.is_file():
            raise ModelError(f"script {self.path} not found")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
            raise ModelError(f"script {self.path} needs a `commands:` list")

    def new_session(
        self, system: str, prompt: str, tools: list[ToolDef], variables: dict[str, Any]
    ) -> ScriptSession:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        commands = [render(str(c), variables) for c in data["commands"]]
        return ScriptSession(commands, str(data.get("final", "done")))


@dataclass
class ScriptSession:
    commands: list[str]
    final: str
    outputs: list[ToolResult] = field(default_factory=list)
    _i: int = 0

    def step(self) -> Turn:
        if self._i >= len(self.commands):
            return Turn(self.final, [], Usage(), "end_turn")
        self._i += 1
        call = ToolCall(f"script_{self._i}", "run_command", {"command": self.commands[self._i - 1]})
        return Turn("", [call], Usage(), "tool_use")

    def add_results(self, results: list[ToolResult]) -> None:
        self.outputs.extend(results)

    def add_message(self, text: str) -> None:
        pass
