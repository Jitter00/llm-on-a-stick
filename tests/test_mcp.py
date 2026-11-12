"""runner/mcp.py: tool schemas, naming and results (no Docker), and the hub against a small stdio server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick import services
from llm_on_a_stick.runner import mcp
from llm_on_a_stick.runner.models import ToolDef
from llm_on_a_stick.services.spec import McpServer

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = FIXTURES / "mcp_tools"
WITH_MCP = ["netbox", "moto", "nautobot", "librenms", "zabbix", "loki"]


def test_sanitize_inlines_references_and_drops_what_models_reject() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Args",
        "type": "object",
        "$defs": {
            "Filter": {"type": "object", "title": "Filter", "properties": {"name": {"type": "string"}}}
        },
        "properties": {
            "filter": {"$ref": "#/$defs/Filter", "description": "what to match"},
            "limit": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}], "default": None},
            "title": {"type": "string", "format": "uri", "pattern": "^a"},  # a property named like a keyword
            "status": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]},
        },
        "required": ["filter"],
        "additionalProperties": False,
    }
    assert mcp.sanitize_schema(schema) == {
        "type": "object",
        "properties": {
            "filter": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "description": "what to match",
            },
            "limit": {"type": "integer"},
            "title": {"type": "string"},
            "status": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        },
        "required": ["filter"],
    }


def test_sanitize_survives_recursion_and_odd_schemas() -> None:
    tree = {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}, "$defs": {}}
    tree["$defs"] = {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}}
    out = mcp.sanitize_schema(tree)
    assert out["properties"]["child"]["properties"]["next"] == {}  # recursion stops: anything goes there
    assert mcp.sanitize_schema(None) == {"type": "object", "properties": {}}
    assert mcp.sanitize_schema({"type": "string"}) == {"type": "object", "properties": {}}
    assert mcp.sanitize_schema({"type": "object"}) == {"type": "object", "properties": {}}


def test_tool_defs_names_filters_and_checks_the_allow_list() -> None:
    tools = [
        {"name": "get", "description": " Get things.\n\nWith details. ", "input_schema": {"type": "object"}},
        {"name": "delete", "description": None, "input_schema": None},
    ]
    defs = mcp.tool_defs("netbox", tools, [])
    assert [d.name for d in defs] == ["netbox__get", "netbox__delete"]
    assert defs[0].description == "Get things.\n\nWith details."  # the server's own words, untouched
    assert [d.name for d in mcp.tool_defs("netbox", tools, ["delete"])] == ["netbox__delete"]
    with pytest.raises(mcp.McpError, match="no tool named gone"):
        mcp.tool_defs("netbox", tools, ["get", "gone"])
    with pytest.raises(mcp.McpError, match="not one a model can call"):
        mcp.tool_defs("netbox", [{"name": "bad name!", "description": "", "input_schema": {}}], [])
    assert mcp.schema_chars(defs) > 0


def test_flatten_keeps_text_and_names_the_rest() -> None:
    class Text:
        type = "text"
        text = "hello"

    class Image:
        type = "image"
        data = "...."

    assert mcp.flatten([Text(), Image(), Text()]) == "hello\n[image omitted]\nhello"
    assert mcp.flatten([]) == ""


@pytest.mark.parametrize("name", WITH_MCP)
def test_every_mcp_server_is_declared_and_fits_a_small_context(name: str) -> None:
    """The snapshot is what the model is shown of the server (tests/integration/test_mcp.py compares it with
    the running server): few enough tools, and a tool list that small context windows can hold."""
    server = services.load(name).mcp
    assert server is not None and server.version
    shown = [ToolDef(**t) for t in json.loads((SNAPSHOTS / f"{name}.json").read_text(encoding="utf-8"))]
    assert 1 <= len(shown) <= 40, f"{name}: {len(shown)} tools"
    assert mcp.schema_chars(shown) <= 24_000, f"{name}: {mcp.schema_chars(shown)} characters"  # ~6k tokens
    for d in shown:
        assert mcp.TOOL_NAME.match(d.name) and d.name.startswith(f"{name}__"), d.name
        assert d.parameters == mcp.sanitize_schema(d.parameters), f"{d.name}: schema not in the subset"
    if server.allow:
        assert [d.name for d in shown] and {d.name.split("__", 1)[1] for d in shown} == set(server.allow)


def test_services_without_an_mcp_block_have_none() -> None:
    assert services.load("oxidized").mcp is None


# --------------------------------------------------------------------------- the hub


def _hub(tmp_path: Path, allow: list[str] | None = None, max_output: int = 4000) -> mcp.McpHub:
    def launcher(_name: str, _server: McpServer) -> list[str]:
        return [sys.executable, str(FIXTURES / "fake_mcp_server.py")]

    server = McpServer(server="fake", version="0", allow=allow or [])
    return mcp.McpHub({"fake": server}, "t1", tmp_path, max_output, launcher=launcher)


def test_hub_lists_calls_and_reports_errors(tmp_path: Path) -> None:
    with _hub(tmp_path, max_output=200) as hub:
        assert [d.name for d in hub.defs] == ["fake__echo", "fake__fail", "fake__slow"]
        assert hub.info["fake"] == {
            "server": "fake",
            "version": "0",
            "tools": ["fake__echo", "fake__fail", "fake__slow"],
            "tools_hidden": 0,
        }
        echo: Any = next(d for d in hub.defs if d.name == "fake__echo")
        assert echo.parameters["properties"]["text"] == {"type": "string"}
        assert echo.parameters["required"] == ["text"]
        assert hub.knows("fake__echo") and not hub.knows("echo")

        res = hub.call("fake__echo", {"text": "hi"})
        assert (res.output, res.is_error, res.timed_out, res.truncated) == ("hi", False, False, False)

        long = hub.call("fake__echo", {"text": "0123456789", "times": 100})
        assert long.truncated and long.output_chars == 1000
        assert "characters omitted. Ask for less" in long.output

        failed = hub.call("fake__fail", {"reason": "no such device"})
        assert failed.is_error and "fail" in failed.output  # the server's text, whatever it says

        bad = hub.call("fake__echo", {"wrong": 1})  # the server's own validation, as text for the model
        assert bad.is_error and not bad.timed_out

        slow = hub.call("fake__slow", {"seconds": 5}, timeout_s=1)
        assert slow.is_error and slow.timed_out and "timed out after 1s" in slow.output
        assert hub.call("fake__echo", {"text": "still here"}).output == "still here"  # the session survives
    assert (tmp_path / "mcp-fake.log").exists()


def test_hub_shows_only_allowed_tools(tmp_path: Path) -> None:
    with _hub(tmp_path, allow=["echo"]) as hub:
        assert [d.name for d in hub.defs] == ["fake__echo"]
        assert hub.info["fake"]["tools_hidden"] == 2
        assert not hub.knows("fake__fail")


def test_hub_says_which_server_did_not_start(tmp_path: Path) -> None:
    def launcher(_name: str, _server: McpServer) -> list[str]:
        return [sys.executable, "-c", "import sys; sys.exit(3)"]

    hub = mcp.McpHub({"netbox": McpServer(server="netbox", version="1")}, "t2", tmp_path, launcher=launcher)
    with pytest.raises(mcp.McpError, match="MCP server netbox did not start"), hub:
        pass
