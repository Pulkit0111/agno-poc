"""Slack App Home — a clickable control panel for the scheduled flows.

A small layer mounted alongside (not replacing) the Agno Slack chat interface: it
renders a Home tab listing the delivery/DSM schedules and handles Add / Run now /
Remove via Block Kit modals. It reuses the already-tested scheduling helpers and the
running AgentOS scheduler — it only adds the surface people click.

The chat interface keeps its own routes (mounted at ``/slack/chat``); this package owns
``/slack/events`` (handling ``app_home_opened`` and forwarding chat events to Agno) and
``/slack/interactivity`` (the buttons + forms).
"""

from __future__ import annotations

from .router import build_slack_home_router

__all__ = ["build_slack_home_router"]
