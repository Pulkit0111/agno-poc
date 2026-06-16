"""GitHub App webhook listener (Phase 3) — port of github-webhook.ts.

Verifies the HMAC signature, handles `pull_request` opened/ready_for_review, dedups
on the delivery id, skips drafts/bots, and enqueues a review task (source=github).
The shared worker (in the Slack app process) picks it up, posts the review to the PR,
and mirrors it to Slack.

Mounted into the same process as the Slack app via interfaces/server.py.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Request, Response

from bott.shared.config import github_webhook_secret, review_slack_channel
from bott.shared.persistence.store import enqueue, seen_delivery

router = APIRouter()

_BOT_AUTHOR_HINTS = ("dependabot", "renovate", "[bot]")


def _verify(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)


@router.post("/webhook/github")
async def github_webhook(request: Request) -> Response:
    secret = github_webhook_secret()
    if not secret:
        return Response(status_code=503, content="webhook secret not configured")

    body = await request.body()
    if not _verify(secret, body, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=401, content="bad signature")

    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")

    if event == "ping":
        return Response(status_code=200, content="pong")
    if event != "pull_request":
        return Response(status_code=202, content="ignored event")

    if seen_delivery(delivery):
        return Response(status_code=202, content="duplicate delivery")

    payload = await request.json()
    action = payload.get("action")
    if action not in ("opened", "ready_for_review"):
        return Response(status_code=202, content="ignored action")

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    if pr.get("draft"):
        return Response(status_code=202, content="draft skipped")
    author = (pr.get("user") or {}).get("login", "").lower()
    if any(h in author for h in _BOT_AUTHOR_HINTS) or (pr.get("user") or {}).get("type") == "Bot":
        return Response(status_code=202, content="bot author skipped")

    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    number = pr.get("number")
    if not (owner and name and number):
        return Response(status_code=202, content="incomplete payload")

    enqueue("review", {
        "source": "github",
        "owner": owner, "name": name, "number": number,
        "title": pr.get("title") or "",
        "author": (pr.get("user") or {}).get("login") or "unknown",
        "channel": review_slack_channel(),  # mirror to Slack if configured
        "thread_ts": None, "trigger_ts": None,
        "post_github": True,
    })
    return Response(status_code=202, content="review enqueued")
