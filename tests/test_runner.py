"""Runner unit tests: model adapters, toolbox output handling, the agent loop and the report. No Docker."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from llm_on_a_stick.grading import grade as grade_mod
from llm_on_a_stick.runner import loop, models, report, toolbox
from llm_on_a_stick.runner.models import ToolCall, ToolResult, Turn, Usage
from llm_on_a_stick.tasks import load_task
from test_grading import DEMO, FRR1, FakeLab

# --------------------------------------------------------------------------- model specs


def test_parse_spec_builtin_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OLLAMA_HOST", "STICK_OLLAMA_BASE_URL", "STICK_STRATA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    m = models.parse_spec("ollama/qwen3:14b")
    assert (m.provider, m.model, m.base_url) == ("ollama", "qwen3:14b", "http://127.0.0.1:11434/v1")
    assert (
        models.parse_spec("strata/qwen", "http://127.0.0.1:9999/v1/").base_url == "http://127.0.0.1:9999/v1"
    )
    monkeypatch.setenv("STICK_STRATA_BASE_URL", "http://10.0.0.5:18500/v1")
    assert models.parse_spec("strata/qwen").base_url == "http://10.0.0.5:18500/v1"
    monkeypatch.setenv("OLLAMA_HOST", "192.168.122.1")  # no port: 11434, like the ollama CLI
    assert models.parse_spec("ollama/x").base_url == "http://192.168.122.1:11434/v1"
    # model names may contain slashes (OpenRouter)
    assert models.parse_spec("openrouter/meta-llama/llama-4").model == "meta-llama/llama-4"


@pytest.mark.parametrize(
    ("spec", "message"),
    [("qwen3", "provider/model"), ("nope/x", "unknown provider"), ("openai-compat/x", "--base-url")],
)
def test_parse_spec_errors(spec: str, message: str) -> None:
    with pytest.raises(models.ModelError, match=message):
        models.parse_spec(spec)


def test_api_models_need_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(models.ModelError, match="OPENAI_API_KEY"):
        models.api_key(models.parse_spec("openai/gpt-x"))
    assert models.api_key(models.parse_spec("ollama/x")) is None  # local servers don't


# --------------------------------------------------------------------------- OpenAI-compatible adapter


class _Server:
    """A tiny OpenAI-compatible server returning canned responses; records the requests."""

    def __init__(self, responses: list[dict[str, Any]], models_: list[str]) -> None:
        self.requests: list[dict[str, Any]] = []
        self.models_meta: dict[str, Any] = {}
        self.disconnected = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._send({"data": [{"id": m, "meta": outer.models_meta} for m in models_]})

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                outer.requests.append(body)
                response = responses.pop(0)
                if not body.get("stream"):
                    self._send(response)
                    return
                events = response if isinstance(response, list) else _as_events(response)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for e in events:
                        self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    outer.disconnected += 1  # the client stopped reading (a loop was spotted)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()


def _as_events(completion: dict[str, Any]) -> list[dict[str, Any]]:
    """A chat completion as the stream of deltas a server would send: text in two pieces, each tool call's
    arguments in two pieces (id and name only in the first), then the finish reason, then the usage."""
    choice = completion["choices"][0]
    msg = choice["message"]
    events: list[dict[str, Any]] = []

    def delta(d: dict[str, Any]) -> None:
        events.append({"choices": [{"index": 0, "delta": d, "finish_reason": None}]})

    for key in ("reasoning_content", "content"):
        text = msg.get(key) or ""
        if text:
            delta({key: text[: len(text) // 2]})
            delta({key: text[len(text) // 2 :]})
    for i, call in enumerate(msg.get("tool_calls") or []):
        fn = call["function"]
        args = fn["arguments"]
        first: dict[str, Any] = {"index": i, "type": "function", "function": {"name": fn["name"]}}
        if call.get("id"):
            first["id"] = call["id"]
        if isinstance(args, dict):
            first["function"]["arguments"] = args
            delta({"tool_calls": [first]})
            continue
        first["function"]["arguments"] = args[: len(args) // 2]
        delta({"tool_calls": [first]})
        delta({"tool_calls": [{"index": i, "function": {"arguments": args[len(args) // 2 :]}}]})
    events.append({"choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]})
    events.append({"choices": [], "usage": completion["usage"]})
    return events


def _completion(content: str = "", calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return {
        "choices": [{"message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def test_openai_adapter_round_trip() -> None:
    server = _Server(
        [
            _completion(calls=[
                {"id": "c1", "type": "function",
                 "function": {"name": "run_command", "arguments": '{"command": "ls"}'}},
                {"type": "function", "function": {"name": "run_command", "arguments": "{not json"}},
            ]),
            _completion("all done"),
        ],
        ["qwen3:14b"],
    )  # fmt: skip
    try:
        client = models.make_client("strata/qwen3:14b", server.url)
        client.check()
        s = client.new_session("sys", "do it", [loop.RUN_COMMAND], {})
        turn = s.step()
        assert [c.arguments for c in turn.tool_calls] == [{"command": "ls"}, None]
        assert turn.tool_calls[1].id == "call_1"  # servers that omit ids get one
        assert (turn.usage.input_tokens, turn.usage.output_tokens) == (100, 20)
        s.add_results([ToolResult("c1", "a b"), ToolResult("call_1", "error", is_error=True)])
        assert s.step().text == "all done"
        sent = server.requests[1]
        assert (sent["temperature"], sent["top_p"]) == (0.6, 0.95)  # qwen3 is in data/sampling.yaml
        assert sent["tools"][0]["function"]["name"] == "run_command"
        assert [m["role"] for m in sent["messages"]] == ["system", "user", "assistant", "tool", "tool"]
        assert sent["messages"][2]["tool_calls"][1]["id"] == "call_1"
    finally:
        server.close()


def test_openai_adapter_cut_off_and_nudge() -> None:
    cut = _completion()
    cut["choices"][0]["finish_reason"] = "length"
    server = _Server([cut, _completion("ok")], ["gemma4:26b"])
    try:
        s = models.make_client("strata/gemma4:26b", server.url).new_session("sys", "go", [], {})
        assert s.step().cut_off
        s.add_message("continue")
        assert not s.step().cut_off
        roles = [(m["role"], m["content"]) for m in server.requests[1]["messages"]]
        assert roles[-2:] == [("assistant", ""), ("user", "continue")]
    finally:
        server.close()


def test_openai_adapter_stops_a_looping_stream() -> None:
    line = "Wait, I'll try `sshpass -p admin ssh admin@172.30.30.12 show configuration` again.\n"
    chunks = [{"choices": [{"index": 0, "delta": {"reasoning": line}}]} for _ in range(5000)]
    server = _Server([chunks, _completion("ok")], ["gemma4:26b"])
    try:
        s = models.make_client("strata/gemma4:26b", server.url).new_session("sys", "go", [], {})
        turn = s.step()
        assert (turn.stop_reason, turn.cut_off, turn.usage_estimated) == ("repetition", True, True)
        assert len(turn.reasoning) < 5000  # stopped after a few thousand characters, not 400,000
        assert turn.usage.output_tokens == len(turn.reasoning) // 4 and turn.usage.input_tokens > 0
        s.add_message("continue")
        assert s.step().text == "ok"
        assert server.requests[1]["messages"][-2] == {
            "role": "assistant",
            "content": "",
        }  # loop not sent back
    finally:
        server.close()


def test_context_window_from_llama_cpp_style_servers() -> None:
    server = _Server([], ["deepseek-v4.1-flash"])
    try:
        client = models.make_client("strata/deepseek-v4.1-flash", server.url)
        server.models_meta = {"n_ctx": 65536}
        client.check()
        assert client.context_window == 65536
    finally:
        server.close()


def test_openai_check_reports_missing_model() -> None:
    server = _Server([], ["llama3.2"])
    try:
        with pytest.raises(models.ModelError, match=r"doesn't serve 'qwen3'.*llama3\.2"):
            models.make_client("ollama/qwen3", server.url).check()
    finally:
        server.close()


def test_openai_unreachable_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models.time, "sleep", lambda _s: None)
    with pytest.raises(models.ModelError, match="cannot reach"):
        models.make_client("ollama/x", "http://127.0.0.1:9/v1").check()


# --------------------------------------------------------------------------- Anthropic adapter


def test_anthropic_session_passes_content_back_unchanged() -> None:
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="Looking."),
        SimpleNamespace(type="tool_use", id="tu1", name="run_command", input={"command": "ls"}),
    ]
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=90,
                            cache_creation_input_tokens=0)  # fmt: skip
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(content=blocks, usage=usage, stop_reason="tool_use")

    client = models.AnthropicClient.__new__(models.AnthropicClient)
    client.spec = models.parse_spec("anthropic/claude-sonnet-5-5")
    client.effort, client.max_output_tokens, client.thinking_param = "high", 16000, None
    client.sdk = SimpleNamespace(APIError=RuntimeError)  # type: ignore[assignment]
    client.client = SimpleNamespace(messages=SimpleNamespace(create=create))  # type: ignore[assignment]

    s = client.new_session("sys", "task", [loop.RUN_COMMAND], {})
    turn = s.step()
    assert turn.text == "Looking."
    assert turn.tool_calls[0].arguments == {"command": "ls"}
    assert turn.usage.input_tokens == 100  # uncached + cache reads: what the model actually read
    assert calls[0]["output_config"] == {"effort": "high"}
    assert "temperature" not in calls[0] and "thinking" not in calls[0]  # --thinking: the model's default
    s.add_results([ToolResult("tu1", "file1")])
    client.thinking_param = {"type": "disabled"}  # the default: off
    s.step()
    assert calls[1]["thinking"] == {"type": "disabled"}
    assert s.messages[1]["content"] is blocks  # thinking blocks go back as received
    assert s.messages[2]["content"][0]["tool_use_id"] == "tu1"


class _BadRequest(Exception):
    pass


def _anthropic_client(accepts: set[str], thinking: bool = False, effort: str | None = None) -> Any:
    """An AnthropicClient whose fake API accepts only these ways of turning thinking off."""
    tried: list[str] = []

    def create(**kwargs: Any) -> Any:
        kind = kwargs["thinking"]["type"]
        tried.append(kind)
        if kind not in accepts:
            raise _BadRequest(kind)
        return SimpleNamespace()

    client = models.AnthropicClient.__new__(models.AnthropicClient)
    client.spec = models.parse_spec("anthropic/some-model")
    client.effort, client.thinking = effort, thinking
    client.thinking_param = None if thinking else {"type": "disabled"}
    client.sampling, client.sampling_source = {"thinking": "on" if thinking else "disabled"}, "default"
    client.sdk = SimpleNamespace(  # type: ignore[assignment]
        BadRequestError=_BadRequest,
        APIError=RuntimeError,
        NotFoundError=KeyError,
        AuthenticationError=KeyError,
        CredentialsError=OSError,
    )
    client.client = SimpleNamespace(  # type: ignore[assignment]
        models=SimpleNamespace(retrieve=lambda model: None), messages=SimpleNamespace(create=create)
    )
    client.check()
    return client, tried


def test_anthropic_missing_credentials_is_a_plain_message() -> None:
    client, _ = _anthropic_client({"disabled"})

    def retrieve(model: str) -> None:
        raise OSError("Credentials file not found")

    client.client.models.retrieve = retrieve
    with pytest.raises(models.ModelError, match="ANTHROPIC_API_KEY"):
        client.check()


def test_anthropic_thinking_is_off_by_default() -> None:
    assert models.make_client.__kwdefaults__ is None  # positional defaults: thinking is the last one
    assert models.make_client.__defaults__[-1] is False  # type: ignore[index]
    client, tried = _anthropic_client({"disabled", "between_tools"})
    assert tried == ["disabled"]
    assert client.thinking_param == {"type": "disabled"} and client.sampling["thinking"] == "disabled"


def test_anthropic_thinking_off_uses_what_the_model_accepts() -> None:
    client, tried = _anthropic_client({"between_tools"})
    assert tried == ["disabled", "between_tools"]
    assert client.thinking_param == {"type": "between_tools"}
    assert client.sampling["thinking"] == "between_tools"


def test_anthropic_model_that_cannot_stop_thinking_is_recorded_as_on() -> None:
    client, tried = _anthropic_client(set())
    assert tried == ["disabled", "between_tools"]
    assert client.thinking_param is None and client.sampling["thinking"] == "on"
    assert "can't be turned off" in client.sampling_source


def test_anthropic_thinking_asked_for_sends_nothing() -> None:
    client, tried = _anthropic_client({"disabled"}, thinking=True)
    assert tried == [] and client.thinking_param is None and client.sampling["thinking"] == "on"


# --------------------------------------------------------------------------- toolbox output


def test_shorten_keeps_head_and_tail() -> None:
    text = "".join(f"line {i}\n" for i in range(5000))
    short = toolbox.shorten(text, 1000)
    assert short.startswith("line 0\n") and short.endswith("line 4999\n")
    assert "characters omitted. Save long output to a file" in short and len(short) < 1200
    assert toolbox.shorten("small", 1000) == "small"


# --------------------------------------------------------------------------- the loop


class FakeToolbox:
    """Executes a few pseudo-commands in Python, so the loop can be tested without Docker."""

    instances: ClassVar[list[FakeToolbox]] = []

    def __init__(
        self, workspace: Path, name: str, max_output: int = 16000, env: dict[str, str] | None = None
    ) -> None:
        self.workspace, self.commands, self.env = workspace, [], env or {}
        FakeToolbox.instances.append(self)

    def __enter__(self) -> FakeToolbox:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def exec(self, command: str, timeout_s: int = 60) -> toolbox.CommandResult:
        self.commands.append(command)
        if command.startswith("save "):  # save <file> <canary>
            _, name, canary = command.split()
            (self.workspace / name).write_text(FRR1.replace("stick-abc12345", canary))
            return toolbox.CommandResult(0, "", 0, False, 0.01)
        if command.startswith("show-config ") and " > /work/" in command:  # show-config <canary> > /work/<f>
            canary, name = command.split()[1], command.split("/work/")[1]
            (self.workspace / name).write_text(FRR1.replace("stick-abc12345", canary))
            return toolbox.CommandResult(0, "", 0, False, 0.01)
        if command.startswith("cat /work/"):
            text = (self.workspace / command.split("/work/")[1]).read_text()
            return toolbox.CommandResult(0, text, len(text), False, 0.01)
        return toolbox.CommandResult(127, "bash: nope: command not found", 30, False, 0.01)


class ListClient:
    """A fake model that plays back a list of turns."""

    def __init__(self, turns: list[Turn], spec: str = "anthropic/claude-sonnet-5-5") -> None:
        self.spec = models.parse_spec(spec)
        self.turns = turns
        self.results: list[ToolResult] = []
        self.messages: list[str] = []

    def check(self) -> None:
        pass

    def new_session(self, system: str, prompt: str, tools: Any, variables: dict[str, Any]) -> Any:
        outer = self

        class S:
            def step(self) -> Turn:
                return outer.turns.pop(0)

            def add_results(self, results: list[ToolResult]) -> None:
                outer.results.extend(results)

            def add_message(self, text: str) -> None:
                outer.messages.append(text)

        return S()


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> Any:
    task = load_task(DEMO)
    task.setup = None
    lab = FakeLab()
    monkeypatch.setattr(loop.toolbox_mod, "Toolbox", FakeToolbox)
    monkeypatch.setattr(grade_mod, "load_task", lambda _: task)
    monkeypatch.setattr(loop.validate_mod, "check_requirements", lambda *_: [])
    FakeToolbox.instances = []
    return task, lab


def _call(command: str, n: int = 1) -> ToolCall:
    return ToolCall(f"c{n}", "run_command", {"command": command}, json.dumps({"command": command}))


def test_scripted_run_passes_and_records_everything(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    script = tmp_path / "solve.yaml"
    script.write_text("commands:\n  - save frr1.cfg {{ canaries.host_desc }}\nfinal: saved\n")
    client = models.make_client(f"script/{script}")
    client.check()

    info, result, m = loop.run_task(task, client, lab, tmp_path / "runs", loop.Settings(seed=3))
    lab.configs["frr1"] = (info.workspace / "frr1.cfg").read_text()  # the device has the canary too
    assert FakeToolbox.instances[0].commands == [f"save frr1.cfg {info.canaries['host_desc']}"]
    assert (m.stop_reason, m.turns, m.tool_calls, m.cost_usd) == ("done", 2, 1, 0.0)

    saved = json.loads((info.run_dir / "result.json").read_text())
    assert saved["metrics"]["model"] == f"script/{script}"
    assert json.loads((info.run_dir / "metrics.json").read_text())["turns"] == 2
    lines = (info.run_dir / "transcript.jsonl").read_text().splitlines()
    kinds = [json.loads(line)["kind"] for line in lines]
    assert kinds == ["start", "turn", "command", "turn", "end"]
    assert result.metrics["limits"]["turns"] == 20  # from the task
    assert result.metrics["limits"]["time_s"] == 3600  # time is only a safety net


def test_loop_limits_bad_calls_and_cost(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    bad = ToolCall("c9", "run_command", None, "{not json")
    turns = [
        Turn("", [_call("nope")], Usage(1000, 100), "tool_use"),
        Turn("", [bad, ToolCall("c8", "shell", {"command": "ls"})], Usage(2000, 100), "tool_use"),
        Turn("", [_call("nope")], Usage(3000, 100), "tool_use"),
    ]
    client = ListClient(turns)
    _, result, m = loop.run_task(task, client, lab, tmp_path / "runs", loop.Settings(max_turns=3))

    assert m.stop_reason == "max_turns"
    assert (m.tool_calls, m.tool_errors, m.command_failures) == (4, 2, 2)
    assert (m.tokens_in, m.tokens_out, m.peak_context_tokens) == (6000, 300, 3100)
    assert m.cost_usd == pytest.approx(6000 * 2 / 1e6 + 300 * 10 / 1e6)  # data/prices.yaml
    assert {"max-turns", "tool-call-error", "no-output"} <= set(result.failure_hints)
    assert result.outcome == "partial"  # the untouched-router checks still pass
    errors = [r for r in client.results if r.is_error]
    assert any("unknown tool 'shell'" in r.output for r in errors)
    assert any("invalid arguments" in r.output for r in errors)


def test_model_error_and_no_tool_use(demo: Any, tmp_path: Path) -> None:
    task, lab = demo

    class Broken(ListClient):
        def new_session(self, *a: Any, **k: Any) -> Any:
            class S:
                def step(self) -> Turn:
                    raise models.ModelError("HTTP 400: model does not support tools")

                def add_results(self, results: list[ToolResult]) -> None:
                    pass

                def add_message(self, text: str) -> None:
                    pass

            return S()

    _, result, m = loop.run_task(task, Broken([], "ollama/tiny"), lab, tmp_path / "a")
    assert (m.stop_reason, m.cost_usd) == ("model_error", 0.0)
    assert "does not support tools" in m.error
    assert "model-error" in result.failure_hints and "no-tool-use" not in result.failure_hints

    silent = ListClient([Turn("I can't", [], Usage(), "end_turn")])
    _, result, m = loop.run_task(task, silent, lab, tmp_path / "b")
    assert m.stop_reason == "done" and "no-tool-use" in result.failure_hints


LOOP = (
    "Let's try `ssh admin@srl2 show configuration`\nWait, I'll try `ssh admin@srl2 show configuration`\n" * 40
)


def test_repeating_detects_loops_not_long_output() -> None:
    assert loop.repeating(LOOP)
    assert loop.repeating(LOOP.replace("\n", " "))  # no line breaks needed
    config = "\n".join(f"set / interface ethernet-1/{i} description port-{i * 7}" for i in range(400))
    assert not loop.repeating(config)
    assert not loop.repeating("short " * 20)


def test_cut_off_reply_gets_one_nudge_then_recovers(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    turns = [
        Turn("", [_call("nope")], Usage(100, 10), "tool_calls"),
        Turn("", [], Usage(200, 16000), "length", reasoning=LOOP),
        Turn("", [_call("nope", 2)], Usage(300, 10), "tool_calls"),
        Turn("done", [], Usage(400, 10), "stop"),
    ]
    client = ListClient(turns, "ollama/looper")
    info, result, m = loop.run_task(task, client, lab, tmp_path / "runs")
    assert (m.stop_reason, m.turns, m.nudges) == ("done", 4, 1)
    assert (m.output_limit_hits, m.repetition_loops) == (1, 1)
    assert client.messages == [loop.NUDGE]
    assert {"output-limit", "repetition-loop"} <= set(result.failure_hints)
    kinds = [json.loads(x)["kind"] for x in (info.run_dir / "transcript.jsonl").read_text().splitlines()]
    assert kinds.count("output_limit") == 1 and kinds.count("nudge") == 1


def test_second_cut_off_ends_the_attempt(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    turns = [
        Turn("", [], Usage(100, 16000), "length", reasoning="thinking without end"),
        Turn("", [], Usage(200, 16000), "max_tokens", reasoning=LOOP),
        Turn("never reached", [], Usage(), "stop"),
    ]
    client = ListClient(turns, "anthropic/claude-sonnet-5-5")
    _, result, m = loop.run_task(task, client, lab, tmp_path / "runs")
    assert (m.stop_reason, m.turns, m.nudges) == ("output_limit", 2, 1)
    assert (m.output_limit_hits, m.repetition_loops) == (2, 1)
    assert {"output-limit", "repetition-loop", "no-tool-use"} <= set(result.failure_hints)


def test_command_from_a_cut_off_reply_is_not_run(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    half = _call("cat << 'EOF' > /work/get_bgp.py\nimport sys\n# Wait, I think")
    turns = [Turn("", [half], Usage(10, 8000), "length"), Turn("ok", [], Usage(), "stop")]
    client = ListClient(turns, "ollama/x")
    info, result, m = loop.run_task(task, client, lab, tmp_path / "runs")
    assert FakeToolbox.instances[-1].commands == []  # never ran
    assert (m.stop_reason, m.tool_calls, m.commands_not_run, m.output_limit_hits, m.nudges) == (
        "done",
        1,
        1,
        1,
        0,
    )
    assert client.results[0].is_error and "not run" in client.results[0].output
    assert "output-limit" in result.failure_hints and "repetition-loop" not in result.failure_hints
    kinds = [json.loads(x)["kind"] for x in (info.run_dir / "transcript.jsonl").read_text().splitlines()]
    assert "command_not_run" in kinds and "command" not in kinds


def test_full_context_window_ends_the_attempt(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    turns = [
        Turn("", [_call("nope")], Usage(1000, 50), "tool_calls"),
        Turn("", [], Usage(65433, 101), "length"),
    ]
    client = ListClient(turns, "ollama/x")
    client.context_window = 65536
    _, result, m = loop.run_task(task, client, lab, tmp_path / "runs")
    assert (m.stop_reason, m.turns, m.nudges, m.output_limit_hits) == ("context_full", 2, 0, 0)
    assert "context-full" in result.failure_hints

    # the same cut-off with room left in the window is an ordinary output-limit hit
    assert not models.context_full(Turn("", [], Usage(20000, 8000), "length"), 65536)
    assert not models.context_full(Turn("", [], Usage(65000, 500), "length"), None)  # window unknown


def test_prompt_names_the_short_workdir_and_sampling_is_recorded(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    client = ListClient([Turn("done", [], Usage(), "stop")], "ollama/x")
    client.sampling = {"temperature": 0.0}
    info, result, _ = loop.run_task(task, client, lab, tmp_path / "runs")
    assert "/work/frr1.cfg" in info.prompt and str(info.workspace) not in info.prompt
    start = json.loads((info.run_dir / "transcript.jsonl").read_text().splitlines()[0])
    assert "Your working directory is /work" in start["system"]
    assert "at most 4000 characters of each command's output" in start["system"]
    assert len(start["system"].split()) < 150  # re-read on every turn: keep it short
    assert result.metrics["limits"]["max_output_chars"] == 4000
    assert result.metrics["sampling"] == {"temperature": 0.0}
    assert result.metrics["system_prompt_version"] == loop.SYSTEM_PROMPT_VERSION


def test_answer_in_reply_when_the_reply_quotes_a_canary(demo: Any, tmp_path: Path) -> None:
    task, lab = demo

    class Quoting(ListClient):
        def new_session(self, system: str, prompt: str, tools: Any, variables: dict[str, Any]) -> Any:
            canary = variables["canaries"]["host_desc"]
            self.turns = [Turn(f"The description is {canary}.", [], Usage(), "stop")]
            return super().new_session(system, prompt, tools, variables)

    _, result, _ = loop.run_task(task, Quoting([], "ollama/x"), lab, tmp_path / "a")
    assert {"no-output", "answer-in-reply"} <= set(result.failure_hints)

    _, result, _ = loop.run_task(task, ListClient([Turn("done", [], Usage(), "stop")]), lab, tmp_path / "b")
    assert "no-output" in result.failure_hints and "answer-in-reply" not in result.failure_hints
    assert not loop.answer_in_reply("ab", {"x": "ab"})  # too short to mean anything


@pytest.mark.parametrize(
    ("model", "temperature", "source"),
    [
        ("gemma4:26b", 1.0, "Gemma 4"),
        ("google/gemma-4-26b-it", 1.0, "Gemma 4"),  # OpenRouter-style name
        ("deepseek-v4.1-flash", 1.0, "DeepSeek V4"),
        ("qwen3:14b", 0.6, "Qwen3"),
        ("Qwen/Qwen3-14B", 0.6, "Qwen3"),  # vLLM-style name, any case
        ("qwen3.5:9b", 0.0, "default"),  # newer Qwen releases differ: not matched
        ("llama3.3:70b", 0.0, "default"),
    ],
)
def test_recommended_sampling_from_the_file(model: str, temperature: float, source: str) -> None:
    values, where = models.recommended_sampling(model)
    assert values["temperature"] == temperature and source in where


def test_temperature_option_overrides_the_file() -> None:
    c = models.make_client("ollama/gemma4:26b", temperature=0.0)
    assert (c.sampling, c.sampling_source) == ({"temperature": 0.0}, "--temperature")
    c = models.make_client("ollama/gemma4:26b")
    assert c.sampling == {"temperature": 1.0, "top_p": 0.95} and "Gemma 4" in c.sampling_source
    assert models.make_client("ollama/unknown-model").sampling == {"temperature": 0.0}


def test_sampling_file_entries_are_complete() -> None:
    for e in models._sampling_entries():
        assert e.get("name") and e.get("source") and e["match"], e
        assert 0 <= e["temperature"] <= 2 and 0 < e.get("top_p", 1) <= 1, e


def test_empty_reply_gets_one_nudge_then_ends_the_attempt(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    turns = [Turn("", [], Usage(500, 280), "stop", reasoning="Plan: ... Let's start b")] * 2
    client = ListClient(turns, "ollama/x")
    _, result, m = loop.run_task(task, client, lab, tmp_path / "a")
    assert (m.stop_reason, m.turns, m.empty_replies, m.nudges) == ("empty_reply", 2, 2, 1)
    assert client.messages == [loop.NUDGE_EMPTY]
    assert "empty-reply" in result.failure_hints

    recovers = [Turn("", [], Usage(), "stop"), Turn("", [_call("nope")], Usage(), "tool_calls")]
    client = ListClient([*recovers, Turn("done", [], Usage(), "stop")], "ollama/x")
    _, _, m = loop.run_task(task, client, lab, tmp_path / "b")
    assert (m.stop_reason, m.turns, m.nudges, m.tool_calls) == ("done", 3, 1, 1)

    # cut-off and empty replies share the one nudge
    shared = [Turn("", [], Usage(), "length", reasoning=LOOP), Turn("", [], Usage(), "stop")]
    _, _, m = loop.run_task(task, ListClient(shared, "ollama/x"), lab, tmp_path / "c")
    assert (m.stop_reason, m.nudges) == ("empty_reply", 1)


def test_cost_unknown_for_unpriced_api_models() -> None:
    assert loop.cost("openai/some-model", False, 1000, 1000) is None
    assert loop.cost("ollama/x", True, 10**6, 10**6) == 0.0


# --------------------------------------------------------------------------- report


def test_report_compares_models(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    runs = tmp_path / "runs"
    loop.run_task(task, ListClient([Turn("no", [], Usage(10, 1), "end_turn")], "ollama/a"), lab, runs)
    b_turns = [
        Turn("", [_call("nope")], Usage(10, 1), "tool_use"),
        Turn("done", [], Usage(20, 2), "end_turn"),
    ]
    loop.run_task(task, ListClient(b_turns, "strata/b"), lab, runs)
    (runs / "by-hand").mkdir()  # a manual run without metrics is ignored
    rows = report.collect([runs])
    assert sorted(r.model for r in rows) == ["ollama/a", "strata/b"]
    summary = {s.model: s for s in report.summarise(rows)}
    assert summary["strata/b"].tokens == 33 and summary["strata/b"].cost_usd == 0.0
    md = report.to_markdown(rows)
    assert "| ollama/a | - | 1 | 0 |" in md and "no-tool-use" in md
    assert json.loads(report.to_json(rows))["models"][0]["model"] == "ollama/a"

    # the same model at another temperature is summarised on its own line
    hot = ListClient([Turn("no", [], Usage(10, 1), "end_turn")], "ollama/a")
    hot.sampling = {"temperature": 1.0, "top_p": 0.95}
    loop.run_task(task, hot, lab, runs)
    lines = {(s.model, s.sampling) for s in report.summarise(report.collect([runs]))}
    assert ("ollama/a", "temperature 1.0, top_p 0.95") in lines and ("ollama/a", "") in lines


def _two_model_runs(
    demo: Any, runs: Path, specs: tuple[str, ...] = ("ollama/a", "ollama/a", "strata/b")
) -> None:
    task, lab = demo
    for spec in specs:
        turns = [
            Turn("", [_call("echo '</script><b>x'")], Usage(10, 1), "tool_use"),
            Turn("no", [], Usage(5, 1), "end"),
        ]
        loop.run_task(task, ListClient(turns, spec), lab, runs)


def test_full_report_and_html(demo: Any, tmp_path: Path) -> None:
    from llm_on_a_stick.grading.results import HINT_TEXT, FailureHint
    from llm_on_a_stick.runner import html

    assert set(HINT_TEXT) == set(FailureHint.__args__)  # type: ignore[attr-defined]
    runs = tmp_path / "runs"
    _two_model_runs(demo, runs)
    attempts = report.collect_attempts([runs])
    assert [(a.model, a.repeat) for a in attempts] == [("ollama/a", 1), ("ollama/a", 2), ("strata/b", 1)]
    assert attempts[0].section == "cfg-mgmt" and attempts[0].title != attempts[0].task_id
    assert any(e["kind"] == "command" for e in attempts[0].events)
    assert "raw_arguments" not in json.dumps(attempts[0].events)

    data = report.build_report(attempts)
    a, b = data["contenders"]
    assert (a["label"], a["attempts"], a["passed"]) == ("ollama/a", 2, 0)
    assert a["struggles"]["never_passed"] == [attempts[0].task_id]
    assert a["struggles"]["failed_checks"][0]["failed"] == 2
    assert a["struggles"]["summary"][0] == "Passed 0 of 2 attempts."
    assert a["total_wall_s"] == pytest.approx(sum(x.metrics["wall_s"] for x in attempts[:2]), abs=0.2)
    assert data["total_wall_s"] == pytest.approx(a["total_wall_s"] + b["total_wall_s"], abs=0.2)
    assert data["tasks"][0]["better"] is None and "Level" in data["versus"]["headline"]
    assert data["turn_limits"] == [attempts[0].metrics["limits"]["turns"]]

    attempts[2].outcome, attempts[2].score = "pass", 1.0  # as if strata/b had passed
    data = report.build_report(attempts)
    assert data["tasks"][0]["better"] == b["id"]
    assert data["versus"]["contenders"] == [a["id"], b["id"]]
    assert data["versus"]["only_passed_by"] == {a["id"]: [], b["id"]: [attempts[0].task_id]}
    assert data["versus"]["headline"].startswith("strata/b did better on 1 of 1 task")

    out = tmp_path / "out" / "report.html"
    assert html.write([runs], out) is not None
    page = out.read_text(encoding="utf-8")
    assert html.PLACEHOLDER not in page
    blob = page.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    assert "<" not in blob and json.loads(blob)["contenders"][0]["model"] == "ollama/a"
    slim = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert "events" not in next(iter(slim["attempts"].values()))
    assert html.write([tmp_path / "nothing"], tmp_path / "none.html") is None


def test_report_compares_up_to_three_models(demo: Any, tmp_path: Path) -> None:
    from llm_on_a_stick.runner import html

    runs = tmp_path / "runs"
    _two_model_runs(demo, runs, ("ollama/a", "strata/b", "strata/c"))
    attempts = report.collect_attempts([runs])
    task_id = attempts[0].task_id

    data = report.build_report(attempts)
    a, b, c = (x["id"] for x in data["contenders"])
    assert data["versus"]["contenders"] == [a, b, c]
    assert data["versus"]["wins"] == {a: [], b: [], c: [], "tie": [task_id]}
    assert data["tasks"][0]["leaders"] == [a, b, c]
    assert data["versus"]["top"] == {a: [task_id], b: [task_id], c: [task_id]}
    assert data["versus"]["headline"] == (
        "Best or joint best on the 1 task all attempted: ollama/a on 1, strata/b on 1, strata/c on 1."
    )

    attempts[2].outcome, attempts[2].score = "pass", 1.0  # as if strata/c alone had passed
    data = report.build_report(attempts)
    assert data["tasks"][0]["better"] == c and data["tasks"][0]["leaders"] == [c]
    assert data["versus"]["only_passed_by"] == {a: [], b: [], c: [task_id]}
    assert data["versus"]["headline"] == (
        "Best or joint best on the 1 task all attempted: strata/c on 1, ollama/a on 0, strata/b on 0."
    )

    attempts[1].outcome, attempts[1].score = "pass", 1.0  # two of the three pass: they share the lead
    data = report.build_report(attempts)
    assert data["tasks"][0]["better"] is None and data["tasks"][0]["leaders"] == [b, c]
    assert data["versus"]["wins"]["tie"] == [task_id]
    assert data["versus"]["top"] == {a: [], b: [task_id], c: [task_id]}
    assert data["versus"]["only_passed_by"] == {a: [], b: [], c: []}

    assert html.write([runs], tmp_path / "three.html") is not None

    # a fourth model: still a report, without the head-to-head
    _two_model_runs(demo, runs, ("strata/d",))
    out = tmp_path / "four.html"
    four = html.write([runs], out)
    assert four is not None and four["versus"] is None and len(four["contenders"]) == 4
    assert html.PLACEHOLDER not in out.read_text(encoding="utf-8")


def test_report_survives_old_runs_and_removed_tasks(demo: Any, tmp_path: Path) -> None:
    task, lab = demo
    runs = tmp_path / "runs"
    info, _, _ = loop.run_task(task, ListClient([Turn("no", [], Usage(1, 1), "end")], "ollama/a"), lab, runs)
    result = json.loads((info.run_dir / "result.json").read_text())
    result["metrics"] = {"model": "ollama/a", "turns": 1}  # an old run: few metrics
    (info.run_dir / "result.json").write_text(json.dumps(result))
    run = json.loads((info.run_dir / "run.json").read_text())
    run["task_dir"] = "/gone/sections/netbox/some-task"  # the task was removed since
    (info.run_dir / "run.json").write_text(json.dumps(run))
    (info.run_dir / "transcript.jsonl").unlink()
    (a,) = report.collect_attempts([runs])
    assert (a.section, a.title, a.events) == ("netbox", a.task_id, [])
    data = report.build_report([a])
    assert data["versus"] is None and data["contenders"][0]["cost_usd"] is None


def test_low_memory_stops_the_attempt(demo: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, lab = demo
    monkeypatch.setattr(loop, "wait_for_ram", lambda _min: 512)
    client = ListClient([Turn("", [_call("nope")], Usage(10, 1), "tool_use")])
    _, result, m = loop.run_task(task, client, lab, tmp_path / "runs", loop.Settings(min_free_ram_mb=2048))
    assert (m.stop_reason, m.turns) == ("low_memory", 0)
    assert "512 MiB RAM free" in m.error and "env-error" in result.failure_hints


def test_wait_for_ram_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    readings = iter([1000, 1500, 4000])
    monkeypatch.setattr(loop, "available_ram_mb", lambda: next(readings))
    monkeypatch.setattr(loop.time, "sleep", lambda _s: None)
    assert loop.wait_for_ram(2048, wait_s=60) == 4000


def test_transcript_hints_are_added_but_never_change_the_outcome(demo: Any, tmp_path: Path) -> None:
    task, lab = demo

    class Saving(ListClient):
        def __init__(self, read_back: bool) -> None:
            super().__init__([], "ollama/x")
            self.read_back = read_back

        def new_session(self, system: str, prompt: str, tools: Any, variables: dict[str, Any]) -> Any:
            canary = variables["canaries"]["host_desc"]
            calls = [_call(f"show-config {canary} > /work/frr1.cfg")]
            if self.read_back:
                calls.append(_call("cat /work/frr1.cfg", 2))
            self.turns = [Turn("", calls, Usage(), "tool_use"), Turn("saved", [], Usage(), "stop")]
            return super().new_session(system, prompt, tools, variables)

    _, unchecked, _ = loop.run_task(task, Saving(read_back=False), lab, tmp_path / "a")
    _, checked, _ = loop.run_task(task, Saving(read_back=True), lab, tmp_path / "b")
    assert "no-verification" in unchecked.failure_hints
    assert "no-verification" not in checked.failure_hints
    assert (unchecked.outcome, unchecked.score) == (checked.outcome, checked.score)
