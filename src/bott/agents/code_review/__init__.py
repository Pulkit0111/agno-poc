"""Code Review specialist — the manager's first member. Wraps the review pipeline and
exposes it both as a Team member (member.py) and via its own direct triggers (cli.py,
webhook.py).
"""
from .core.models import ReviewOutput
from .core.pipeline import ReviewResult, review_pr
from .core.verdict_gate import GateResult, apply_gate
from .member import (
    ReviewTarget,
    build_code_review_agent,
    reset_review_target,
    review_tools,
    set_review_target,
)

__all__ = [
    "review_pr", "ReviewResult", "ReviewOutput", "GateResult", "apply_gate",
    "build_code_review_agent", "ReviewTarget", "review_tools",
    "set_review_target", "reset_review_target",
]
