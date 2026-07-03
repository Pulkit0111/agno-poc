from __future__ import annotations

from typing import Callable, Optional

from agno.run.base import RunContext

from bott.agents.build_fix.core.models import BuildRequest
from bott.agents.build_fix.refs import parse_build_target, parse_repo_ref
from bott.shared.config import allowed_post_repos, bott_model
from bott.shared.persistence import queue


def _target(run_context: Optional[RunContext]) -> dict:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    return {"channel": deps.get("Slack channel_id"), "thread_ts": deps.get("Slack thread_ts")}


def start_build(target: str, repo: str = "", run_context: Optional[RunContext] = None) -> str:
    """Plan and (after you approve) implement ONE cohesive change, opening ONE pull request.

    One call = one plan = one pull request. If the user asks for SEVERAL independent PRs
    (e.g. "one PR per project", "separate PRs for each"), call this ONCE PER PR.

    ALWAYS pass ``repo`` when you know which repo to work on (e.g. from the conversation) —
    e.g. repo="pulkit0111/moodflix". Don't rely on the repo being scraped from the change
    description; a phrase like "the docs/auth mismatch" is NOT a repo.

    Args:
        target: what to build — a plain description of the change, a GitHub issue
            ("owner/repo#123" or its URL), or a Jira key ("PADI-42").
        repo: the target repo as "owner/repo" (or its GitHub URL). Authoritative when given.
    """
    req = parse_build_target(target)
    # Explicit repo wins over anything scraped from the description (parsed directly, so a
    # deliberately-passed owner/repo isn't dropped by the prose allowlist gate).
    if repo.strip():
        o, n = parse_repo_ref(repo)
        if o and n:
            req = BuildRequest(kind=req.kind if req.kind in ("github_issue", "jira") else "request",
                               text=target or repo, owner=o, repo=n,
                               issue=req.issue, jira_key=req.jira_key)

    # Fail fast with ONE coherent reply, rather than "On it" followed by a background refusal.
    allow = {r.lower() for r in allowed_post_repos()}
    if req.kind in ("request", "github_issue"):
        if not (req.owner and req.repo):
            return ("Which repo should I build on? Give me an `owner/repo` I have write access "
                    "to (e.g. `pulkit0111/moodflix`).")
        if allow and f"{req.owner}/{req.repo}".lower() not in allow:
            return (f"I can only open PRs on allow-listed repos, and `{req.owner}/{req.repo}` "
                    "isn't one. Point me at an allowed repo, or ask an admin to add it.")

    t = _target(run_context)
    user_id = getattr(run_context, "user_id", None) or "system@axelerant.com"
    queue.enqueue("plan", {
        "kind": req.kind, "owner": req.owner, "repo": req.repo, "issue": req.issue,
        "jira_key": req.jira_key, "text": req.text,
        "channel": t["channel"], "thread_ts": t["thread_ts"],
        "model_id": bott_model(),
    }, user_id=user_id)
    return "On it — I'll read the context, draft a plan, and post it here for your approval."


def build_tools() -> list[Callable]:
    return [start_build]
