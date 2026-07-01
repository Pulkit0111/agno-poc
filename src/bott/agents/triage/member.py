from __future__ import annotations

import contextvars
from typing import Callable, Optional

from agno.run.base import RunContext

from bott.shared.config import bott_model
from bott.shared.persistence import queue

_triage_target: contextvars.ContextVar = contextvars.ContextVar("triage_target", default=None)


def _resolve_target(run_context: Optional[RunContext]) -> dict:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    channel = deps.get("Slack channel_id")
    if channel:
        return {"channel": channel, "thread_ts": deps.get("Slack thread_ts")}
    return _triage_target.get() or {}


def start_triage(sentry_issue_id: str, repo: str, run_context: Optional[RunContext] = None) -> str:
    """Triage a Sentry incident: read it, diagnose it, propose a fix, await approval, then
    implement. `sentry_issue_id`: the Sentry issue id. `repo`: the `owner/name` GitHub repo to
    fix (Sentry doesn't know the repo — you must name it)."""
    parts = (repo or "").strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return "Tell me which repo to fix as `owner/name` (e.g. `axelerant/foo`)."
    owner, name = parts[0], parts[1]
    sid = (sentry_issue_id or "").strip()
    if not sid:
        return "Which Sentry issue? Give me its id."
    t = _resolve_target(run_context)
    user_id = getattr(run_context, "user_id", None) or "system@axelerant.com"
    queue.enqueue("triage", {
        "sentry_issue_id": sid, "owner": owner, "name": name,
        "channel": t.get("channel"), "thread_ts": t.get("thread_ts"),
        "model_id": bott_model(),
    }, user_id=user_id)
    return f"Queued triage of Sentry issue {sid} in {owner}/{name} — I'll diagnose it and post a proposed fix for approval."


def triage_tools() -> list[Callable]:
    return [start_triage]
