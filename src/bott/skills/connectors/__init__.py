"""Read-only shared connectors (Jira, Confluence, Slack-thread). Each tool is gated on its
credentials; build_bott_agent wires whatever is available."""

from typing import Callable


def connector_tools() -> list[Callable]:
    from .confluence_read import confluence_read_tools
    from .jira_read import jira_read_tools
    from .slack_read import slack_read_tools

    tools: list = []
    tools += jira_read_tools()
    tools += confluence_read_tools()
    tools += slack_read_tools()
    return tools
