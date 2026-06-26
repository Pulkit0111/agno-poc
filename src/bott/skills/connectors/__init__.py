"""Read-only shared connectors (Jira, Confluence, Slack-thread). Each tool is gated on its
credentials; build_bott_agent wires whatever is available."""

from typing import Callable


def connector_tools() -> list[Callable]:
    from .jira_read import jira_read_tools

    return list(jira_read_tools())
