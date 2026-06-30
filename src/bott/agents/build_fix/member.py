from __future__ import annotations

from typing import Callable, Optional

from agno.run.base import RunContext

from bott.agents.build_fix.refs import parse_build_target
from bott.shared.config import bott_model
from bott.shared.persistence import queue


def _target(run_context: Optional[RunContext]) -> dict:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    return {"channel": deps.get("Slack channel_id"), "thread_ts": deps.get("Slack thread_ts")}


def start_build(target: str, run_context: Optional[RunContext] = None) -> str:
    """Plan and (after you approve) implement a change, opening a draft PR.

    Args:
        target: what to build — a plain description ("add X to owner/repo"), a GitHub issue
            ("owner/repo#123" or its URL), or a Jira key ("PADI-42").
    """
    req = parse_build_target(target)
    t = _target(run_context)
    user_id = getattr(run_context, "user_id", None) or "system@axelerant.com"
    queue.enqueue("plan", {
        "kind": req.kind, "owner": req.owner, "repo": req.repo, "issue": req.issue,
        "jira_key": req.jira_key, "text": req.text,
        "channel": t["channel"], "thread_ts": t["thread_ts"],
        "model_id": bott_model(),
    }, user_id=user_id)
    return "Queued — I'll read the context, draft a plan, and post it here for your approval."


def build_tools() -> list[Callable]:
    return [start_build]
