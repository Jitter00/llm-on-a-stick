"""Tool-stack services (NetBox, Nautobot, ...), each described by services/<name>/service.yaml."""

from llm_on_a_stick.services.spec import ServiceSpec, available, load

__all__ = ["ServiceSpec", "available", "load"]
