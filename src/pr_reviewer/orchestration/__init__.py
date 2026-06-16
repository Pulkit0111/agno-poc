"""Orchestration layer — the conversational manager (an Agno Team leader) and the
specialist member agents it delegates to. The manager owns conversation + routing;
the specialists own the actual work (the Code Review specialist hands long-running
reviews to the durable worker rather than blocking the chat)."""

from .code_review_agent import SlackContext, build_code_review_agent, make_review_tools
from .manager import build_manager, run_manager

__all__ = [
    "SlackContext",
    "build_code_review_agent",
    "make_review_tools",
    "build_manager",
    "run_manager",
]
