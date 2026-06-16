"""Code Review specialist — the manager's first member. Wraps the review pipeline and
exposes it both as a Team member (member.py) and via its own direct triggers (cli.py,
webhook.py).
"""
from .core.models import ReviewOutput
from .core.pipeline import ReviewResult, review_pr
from .core.verdict_gate import GateResult, apply_gate
from .member import SlackContext, build_code_review_agent, make_review_tools

__all__ = [
    "review_pr", "ReviewResult", "ReviewOutput", "GateResult", "apply_gate",
    "build_code_review_agent", "SlackContext", "make_review_tools",
]
