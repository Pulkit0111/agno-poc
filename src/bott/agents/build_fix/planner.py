from __future__ import annotations

import json
from typing import Callable

from bott.agents.build_fix import rendering
from bott.agents.build_fix.core.models import ImplementPlan
from bott.shared.config import allowed_post_repos
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.build_fix.planner")


def run_plan_job(args: dict, *, post: Callable, create_approval: Callable) -> dict:
    """Enforce the write allowlist, then create the approval row (carrying the implement
    payload) and post the plan with Approve/Dismiss buttons.

    `post(channel, thread_ts, blocks, fallback)` and `create_approval(user_id, action,
    summary, payload)` are injected so this is unit-testable offline. `args` must include
    owner/name/plan_text/channel/thread_ts/user_id (plan_text is produced upstream)."""
    owner = args.get("owner")
    name = args.get("name") or args.get("repo")
    channel, thread_ts = args.get("channel"), args.get("thread_ts")
    if not owner or not name:
        if channel:
            post(channel, thread_ts,
                 [{"type": "section", "text": {"type": "mrkdwn",
                   "text": "I couldn't tell which repo to build on — give me an `owner/repo`"
                           " (e.g. `Pulkit0111/bott-pr-review-harness`)."}}],
                 "Couldn't resolve target repo.")
        return {"status": "no_repo", "approval_id": None}
    if f"{owner}/{name}".lower() not in allowed_post_repos():
        if channel:
            post(channel, thread_ts,
                 [{"type": "section", "text": {"type": "mrkdwn",
                   "text": f"I can't open PRs on `{owner}/{name}` (not in the allowlist)."}}],
                 "Repo not allow-listed.")
        return {"status": "refused_not_allowlisted", "approval_id": None}

    plan = ImplementPlan(summary=args["plan_text"])  # plan_text already drafted upstream
    payload = json.dumps({"owner": owner, "name": name, "plan_text": args["plan_text"],
                          "channel": channel, "thread_ts": thread_ts})
    approval_id = create_approval(user_id=args.get("user_id") or "system@axelerant.com",
                                  action="build:implement",
                                  summary=f"Implement on {owner}/{name}: {args['plan_text'][:80]}",
                                  payload=payload)
    blocks, fallback = rendering.plan_blocks(plan, approval_id)
    if channel:
        post(channel, thread_ts, blocks, fallback)
    return {"status": "awaiting_approval", "approval_id": approval_id}
