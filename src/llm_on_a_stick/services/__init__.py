"""Tool-stack services (NetBox, Nautobot, ...), each described by services/<name>/service.yaml."""

from llm_on_a_stick.services.spec import (
    McpServer,
    ServiceSpec,
    available,
    lab_mcp_servers,
    load,
    mcp_server,
    with_mcp,
)

__all__ = ["McpServer", "ServiceSpec", "available", "lab_mcp_servers", "load", "mcp_server", "with_mcp"]
