"""pr_reviewer — an Agno-powered PR review application.

A code-review pipeline (a scoped re-implementation of Bott's reviewer): fetch a PR,
shallow-clone it, let an Agno agent investigate with tools, run the verdict gate over
the model's output, and render a GitHub review and/or Slack message. Drive it from the
CLI (`pr-review`), the Slack bot, or the GitHub webhook (`pr-review-server`).

This module re-exports the stable public surface so callers don't depend on internal
module layout.
"""

from __future__ import annotations

from .core.models import ReviewOutput
from .core.pipeline import ReviewResult, review_pr
from .core.verdict_gate import GateResult, apply_gate

__all__ = [
    "review_pr",
    "ReviewResult",
    "ReviewOutput",
    "GateResult",
    "apply_gate",
]
