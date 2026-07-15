from __future__ import annotations

import json
from typing import Callable

from bott.agents.triage import rendering
from bott.shared.config import allowed_post_repos, sentry_configured
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.triage")


def _default_fetch(sentry_issue_id: str):
    from bott.shared import config
    from bott.shared.integrations.sentry import SentryClient
    c = SentryClient(base_url=config.sentry_base_url(), org_slug=config.sentry_org_slug(),
                     api_token=config.sentry_api_token())
    return c.get_issue(sentry_issue_id), c.issue_events(sentry_issue_id, limit=5)


def _default_diagnose(issue: dict, events: list) -> tuple[str, str]:
    """Diagnose via `codex exec` (the org ChatGPT subscription — the only LLM path in
    bott); split its output into (diagnosis, fix_brief). No repo checkout is involved, so
    it runs in an empty temp cwd, read-only sandbox, ephemeral session."""
    import tempfile

    from bott.agents.triage.agent.prompt import TRIAGE_SYSTEM
    from bott.shared import codex_cli, config
    from bott.shared import model as model_mod
    context = json.dumps({"issue": issue, "events": events}, default=str)[:6000]
    with tempfile.TemporaryDirectory(prefix="bott-triage-") as cwd:
        result = codex_cli.run_codex_exec(
            f"{TRIAGE_SYSTEM}\n\nTriage this incident:\n{context}",
            cwd=cwd, sandbox="read-only", ephemeral=True,
            model_id=model_mod.resolve_model_id("build"),
            timeout_s=config.codex_cli_timeout_s(),
            binary=config.codex_cli_binary())
    out = result.text
    if "FIX:" in out:
        diag, brief = out.split("FIX:", 1)
        return diag.strip(), brief.strip()
    return out.strip(), out.strip()


def run_triage_job(args: dict, *, post: Callable, create_approval: Callable,
                   fetch: Callable | None = None, diagnose: Callable | None = None) -> dict:
    """Read the Sentry issue, diagnose it, enforce the write allowlist, create the implement
    approval (payload shaped like a build plan) and post the diagnosis + Approve/Dismiss.
    Deps injected for offline tests (like run_plan_job)."""
    owner, name = args["owner"], args["name"]
    channel, thread_ts = args.get("channel"), args.get("thread_ts")
    if fetch is None and not sentry_configured():
        if channel:
            post(channel, thread_ts, [{"type": "section", "text": {"type": "mrkdwn",
                 "text": "Sentry isn't configured (set SENTRY_ORG_SLUG, SENTRY_API_TOKEN)."}}],
                 "Sentry not configured.")
        return {"status": "sentry_unconfigured", "approval_id": None}
    if f"{owner}/{name}".lower() not in allowed_post_repos():
        if channel:
            post(channel, thread_ts, [{"type": "section", "text": {"type": "mrkdwn",
                 "text": f"I can't open PRs on `{owner}/{name}` (not in the allowlist)."}}],
                 "Repo not allow-listed.")
        return {"status": "refused_not_allowlisted", "approval_id": None}

    fetch = fetch or _default_fetch
    diagnose = diagnose or _default_diagnose
    try:
        issue, events = fetch(args["sentry_issue_id"])
    except Exception as e:  # noqa: BLE001
        log.error("triage fetch failed: %s", e)
        if channel:
            post(channel, thread_ts, [{"type": "section", "text": {"type": "mrkdwn",
                 "text": "Couldn't read that Sentry issue."}}], "Sentry read failed.")
        return {"status": "fetch_failed", "approval_id": None}
    diagnosis, brief = diagnose(issue, events)
    payload = json.dumps({"owner": owner, "name": name, "plan_text": brief,
                          "channel": channel, "thread_ts": thread_ts})
    approval_id = create_approval(user_id=args.get("user_id") or "system@axelerant.com",
                                  action="triage:implement",
                                  summary=f"Fix {owner}/{name} (Sentry {args['sentry_issue_id']}): {brief[:80]}",
                                  payload=payload)
    blocks, fallback = rendering.triage_blocks(diagnosis, issue.get("permalink", ""), approval_id)
    if channel:
        post(channel, thread_ts, blocks, fallback)
    return {"status": "awaiting_approval", "approval_id": approval_id}
