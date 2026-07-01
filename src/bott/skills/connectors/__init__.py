"""Connector wiring. The REGISTRY is the single source of truth; connector_tools() is kept
as a back-compat shim that registers all connectors then returns their flattened tools."""

from typing import Callable


def connector_tools() -> list[Callable]:
    from .register_all import register_all
    from .registry import REGISTRY

    register_all()
    return REGISTRY.all_tools()
