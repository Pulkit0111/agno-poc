"""Register every connector into the process-wide REGISTRY exactly once. This is THE
connector wiring path — build_agent reads REGISTRY.all_tools(). Existing connectors are
wrapped as thin FunctionConnector entries (internals untouched); Gmail is domain-delegated."""

from __future__ import annotations

from bott.shared.config import memra_configured
from bott.shared.context import MemraClient, make_memra_tools
from bott.skills.connectors.confluence_read import confluence_read_tools
from bott.skills.connectors.gmail import gmail_read_tools
from bott.skills.connectors.jira_read import jira_read_tools
from bott.skills.connectors.registry import REGISTRY, FunctionConnector
from bott.skills.connectors.slack_read import slack_read_tools


def _memra_tools():
    # Gating stays inside the factory: never instantiate MemraClient unless configured.
    return make_memra_tools(MemraClient()) if memra_configured() else []


def register_all() -> None:
    """Idempotent: registers all connectors on first call, no-ops thereafter."""
    if REGISTRY.all_connectors():
        return
    REGISTRY.register(FunctionConnector("jira", "org_credential", jira_read_tools))
    REGISTRY.register(FunctionConnector("confluence", "org_credential", confluence_read_tools))
    REGISTRY.register(FunctionConnector("slack", "org_credential", slack_read_tools))
    REGISTRY.register(FunctionConnector("memra", "org_credential", _memra_tools))
    REGISTRY.register(FunctionConnector("gmail", "domain_delegated", gmail_read_tools))
