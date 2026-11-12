"""A tiny MCP server on stdio for the unit tests of runner/mcp.py: three tools, no network."""

import time

from mcp.server.mcpserver import MCPServer

server = MCPServer("fake")


@server.tool()
def echo(text: str, times: int = 1) -> str:
    """Return the text, `times` times."""
    return text * times


@server.tool()
def fail(reason: str) -> str:
    """Always fails."""
    raise ValueError(reason)


@server.tool()
def slow(seconds: float) -> str:
    """Answers after `seconds`."""
    time.sleep(seconds)
    return "done"


if __name__ == "__main__":
    server.run()
