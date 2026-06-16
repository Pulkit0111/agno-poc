"""Bott-POC Slack app (Phase 2) — primary interface for the review engine.

Socket Mode (no public URL). `@bott-poc review <PR-URL>` queues a review; the worker
runs the Phase-1 engine and posts the verdict in-thread. Replies in a review thread
(or the Re-review button) drive an evidence-bound re-review.

Run:  python -m bott.interfaces.slack_app
"""

from __future__ import annotations

import json
import os
import re
import time

# The python.org Python build ships without CA certs; slack_sdk uses urllib (not
# httpx), so point its default SSL context at certifi's bundle before any Slack call.
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(certifi.where()))

from dotenv import load_dotenv

load_dotenv()

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from bott.agents.code_review.github.app_auth import app_token_for
from bott.agents.code_review.member import SlackContext
from bott.manager import build_manager, stream_manager
from bott.shared.config import allowed_post_repos, default_budget
from bott.shared.observability.logging_setup import get_logger

log = get_logger("review.slack")
from bott.agents.code_review.core.models import ReviewOutput
from bott.agents.code_review.core.pipeline import review_pr
from bott.agents.code_review.core.rereview import build_prior_review, build_prior_review_text
from bott.agents.code_review.core.verdict_gate import GateResult
from bott.agents.code_review.rendering.slack import render_slack_review
from bott.shared.persistence.store import (
    Task,
    Worker,
    enqueue,
    init_db,
    latest_trace_for_thread,
    recover_orphans,
    save_trace,
)

# Per-review budget from env (lean defaults so a run fits low OpenAI TPM tiers).
REVIEW_BUDGET = default_budget()

_VERDICT_EMOJI = {"approve": "white_check_mark", "suggestions": "bulb", "issues": "no_entry"}

app = App(token=os.environ["SLACK_BOT_TOKEN"])
_bot_user_id: str | None = None


def _react(channel: str, ts: str, name: str, add: bool = True) -> None:
    try:
        if add:
            app.client.reactions_add(channel=channel, timestamp=ts, name=name)
        else:
            app.client.reactions_remove(channel=channel, timestamp=ts, name=name)
    except Exception:
        pass  # reactions are cosmetic; never fail the review over them


def _post(channel: str, thread_ts: str, blocks: list[dict], fallback: str) -> str:
    return app.client.chat_postMessage(
        channel=channel, thread_ts=thread_ts, blocks=blocks, text=fallback
    )["ts"]


def _update(channel: str, ts: str, blocks: list[dict], fallback: str) -> None:
    try:
        app.client.chat_update(channel=channel, ts=ts, blocks=blocks, text=fallback)
    except Exception:
        pass  # a dropped progress edit must never fail the review


# High-level stages shown as a Bott-style checklist (not per-tool spam).
_STAGES = [
    ("fetch", "Fetch PR details"),
    ("clone", "Clone the repo"),
    ("review", "Review the code"),
    ("verdict", "Decide the verdict"),
]
_TALLY = [
    ("read_file", "read", "reads"),
    ("search_code", "search", "searches"),
    ("find_references", "ref lookup", "ref lookups"),
    ("get_file_history", "history check", "history checks"),
]


def _tally_text(counts: dict) -> str:
    parts = []
    for name, sing, plur in _TALLY:
        n = counts.get(name, 0)
        if n:
            parts.append(f"{n} {sing if n == 1 else plur}")
    if counts.get("read_review_rules"):
        parts.append("review rules")
    return " · ".join(parts)


def _checklist_blocks(number: int, verb: str, current_key: str, counts: dict) -> list[dict]:
    """A calm one-line progress indicator: monochrome step dots + a compact stage line.
    ●=done  ◐=in progress  ○=pending."""
    cur = next((i for i, (k, _) in enumerate(_STAGES) if k == current_key), 0)
    dots = "".join("●" if i < cur else ("◐" if i == cur else "○") for i in range(len(_STAGES)))
    head = f"{dots}  {verb} PR #{number}"
    tally = _tally_text(counts)
    if tally:
        head += f"  ·  {tally}"
    marks = []
    for i, (key, _label) in enumerate(_STAGES):
        marks.append(f"{key} ✓" if i < cur else (f"{key} …" if i == cur else key))
    text = f"*{head}*\n_{'  '.join(marks)}_"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


# ── worker handler ────────────────────────────────────────────────────────────
def handle_task(task: Task) -> None:
    a = task.args
    channel, thread_ts, trigger_ts = a.get("channel"), a.get("thread_ts"), a.get("trigger_ts")
    source = a.get("source", "slack")  # "slack" or "github" (webhook auto-trigger)

    log.info("task %s: %s source=%s", task.id, task.kind, source)
    if task.kind == "review":
        owner, name, number = a["owner"], a["name"], a["number"]
        prior_review = prior_text = prior_verdict = None
    else:  # rereview (Slack-thread only)
        prior = latest_trace_for_thread(channel, thread_ts) if channel else None
        if not prior:
            if channel:
                _post(channel, thread_ts, [
                    {"type": "section", "text": {"type": "mrkdwn",
                     "text": "I don't have a prior review in this thread to re-review."}}
                ], "No prior review in this thread.")
            return
        owner, name, number = prior["owner"], prior["name"], prior["pr_number"]
        prior_output = ReviewOutput.model_validate_json(prior["output_json"])
        prior_verdict = prior["final_verdict"]
        prior_review = build_prior_review(prior_output, prior_verdict)
        prior_text = build_prior_review_text(prior_output, prior_verdict, a.get("reply_text", ""))

    # Live progress is shown in Slack only when we have a channel (Slack-triggered, or
    # a webhook review with REVIEW_SLACK_CHANNEL configured). Webhook reviews with no
    # channel post only to GitHub.
    verb = "Re-reviewing" if task.kind == "rereview" else "Reviewing"
    counts: dict[str, int] = {}
    state = {"key": "fetch"}

    # Auto (webhook) reviews post a parent announcement in the channel; the review
    # itself lives as a threaded reply under it (matches Bott). Slack-triggered
    # reviews reply in the existing thread.
    review_thread_ts = thread_ts
    if source == "github" and channel:
        title = a.get("title") or ""
        author = a.get("author") or "unknown"
        ann = (f":mag: *Auto-reviewing* "
               f"<https://github.com/{owner}/{name}/pull/{number}|{owner}/{name}#{number}>")
        if title:
            ann += f": {title}"
        ann += f" — by `{author}`"
        review_thread_ts = _post(
            channel, None, [{"type": "section", "text": {"type": "mrkdwn", "text": ann}}],
            f"Auto-reviewing {owner}/{name}#{number}",
        )

    status_ts = (
        _post(channel, review_thread_ts, _checklist_blocks(number, verb, "fetch", counts),
              f"{verb} PR #{number}…")
        if channel else None
    )

    def on_progress(stage_key: str) -> None:
        state["key"] = stage_key
        if status_ts:
            _update(channel, status_ts, _checklist_blocks(number, verb, stage_key, counts),
                    f"{verb} PR #{number}")

    def on_tool(tool_name: str, args: dict) -> None:
        counts[tool_name] = counts.get(tool_name, 0) + 1
        if status_ts:
            _update(channel, status_ts, _checklist_blocks(number, verb, state["key"], counts),
                    f"{verb} PR #{number}")

    # Authenticate as the App for BOTH sources — the engine needs a token to read/clone
    # private repos (without it, the GitHub API 404s). app_token_for raises when the App
    # isn't installed on the repo (e.g. an arbitrary public repo someone pastes); fall
    # back to the PAT / unauthenticated path in that case. Posting stays webhook-only
    # (allowlist-guarded); Slack-triggered reviews remain Slack-only.
    do_post = False
    try:
        gh_token = app_token_for(owner, name)
    except Exception as e:  # noqa: BLE001 — App not installed on this repo, etc.
        log.info("no App token for %s/%s (%s); falling back to PAT/unauthenticated", owner, name, e)
        gh_token = None
    if source == "github":
        do_post = bool(a.get("post_github")) and f"{owner}/{name}".lower() in allowed_post_repos()

    def _fail(text_md: str, fallback: str) -> None:
        if trigger_ts:
            _react(channel, trigger_ts, "eyes", add=False)
            _react(channel, trigger_ts, "warning")
        if status_ts:
            _update(channel, status_ts,
                    [{"type": "section", "text": {"type": "mrkdwn", "text": text_md}}], fallback)

    try:
        result = review_pr(
            owner, name, number,
            budget=REVIEW_BUDGET, token=gh_token, post=do_post,
            prior_review=prior_review, prior_review_text=prior_text,
            on_progress=on_progress, on_tool=on_tool,
        )
    except Exception as e:  # fetch/clone/transport failure (e.g. GitHub rate limit)
        log.warning("review error %s/%s#%s: %s", owner, name, number, e)
        m = str(e).lower()
        friendly = ("GitHub's API rate limit is temporarily exhausted on my end. Give it a few "
                    "minutes and tag me again."
                    if ("rate limit" in m or "403" in m or "429" in m)
                    else "Something went wrong setting up the review. Please try again in a moment.")
        _fail(f":warning: I couldn't start reviewing PR #{number} just now.\n{friendly}",
              f"Couldn't start reviewing PR #{number}")
        return

    if result.run.output is None:
        log.warning("review incomplete %s/%s#%s termination=%s error=%s", owner, name, number, result.run.termination, result.run.error)
        friendly = _friendly_failure(result.run.termination, result.run.error)
        _fail(f":warning: I couldn't finish reviewing <{result.meta.url}|PR #{number}> just now.\n{friendly}",
              f"Couldn't finish reviewing PR #{number}")
        return

    gate: GateResult = result.gate  # type: ignore[assignment]
    log.info("review done %s/%s#%s verdict=%s tool_calls=%s cost=%s posted=%s",
             owner, name, number, gate.final_verdict, len(result.run.tool_calls),
             result.run.cost_usd, bool(result.posted))
    rendered = render_slack_review(
        result.run.output, gate,
        owner=owner, name=name, number=number, url=result.meta.url,
        tool_calls=result.run.tool_calls, prior_verdict=prior_verdict,
    )
    blocks = list(rendered.blocks)
    if result.posted:
        url = result.posted.get("html_url", result.meta.url)
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": f":white_check_mark: Posted to the PR on GitHub — <{url}|view review>"}]})

    if status_ts:
        _update(channel, status_ts, blocks, rendered.fallback)  # morph status into review

    if trigger_ts:
        _react(channel, trigger_ts, "eyes", add=False)
        _react(channel, trigger_ts, _VERDICT_EMOJI.get(gate.final_verdict, "white_check_mark"))

    if channel:  # persist for re-review continuity (keyed by the Slack thread)
        save_trace(
            channel=channel, thread_ts=review_thread_ts or status_ts or "",
            owner=owner, name=name, pr_number=number,
            original_verdict=gate.original_verdict, final_verdict=gate.final_verdict,
            output_json=result.run.output.model_dump_json(),
            gate_json=json.dumps({"outcome": gate.outcome, "downgrade_reason": gate.downgrade_reason}),
        )


# ── conversational core ─────────────────────────────────────────────────────────
_user_names: dict[str, str] = {}


def _display_name(user_id: str) -> str:
    """Human name for a Slack user id (cached). Falls back to the id."""
    if not user_id:
        return "someone"
    if user_id in _user_names:
        return _user_names[user_id]
    name = user_id
    try:
        info = app.client.users_info(user=user_id)["user"]
        name = info.get("profile", {}).get("display_name") or info.get("real_name") or user_id
    except Exception:
        pass
    _user_names[user_id] = name
    return name


def _thread_transcript(channel: str, thread_ts: str, limit: int = 30) -> str:
    """The whole Slack thread, oldest→newest, as a labelled transcript so the manager
    has the full conversation in context (every participant, not just the last message)."""
    try:
        msgs = app.client.conversations_replies(channel=channel, ts=thread_ts, limit=limit).get(
            "messages", []
        )
    except Exception as e:  # noqa: BLE001 — context is best-effort; never block a reply
        log.info("could not fetch thread %s/%s: %s", channel, thread_ts, e)
        return ""
    lines = []
    for m in msgs:
        if m.get("subtype"):
            continue
        speaker = "Bott" if (m.get("bot_id") or m.get("user") == _bot_user_id) else _display_name(m.get("user", ""))
        body = _strip_mention(m.get("text", "")).strip()
        if body:
            lines.append(f"{speaker}: {body}")
    return "\n".join(lines)


def _converse(channel: str, thread_ts: str, trigger_ts: str, text: str, prior_row) -> None:
    """Run the manager (Team leader) on the message with the FULL thread as context, so it
    follows the whole conversation. It chats directly, or delegates to the Code Review
    specialist whose tool queues work onto the durable worker (which posts the verdict)."""
    ctx = SlackContext(channel=channel, thread_ts=thread_ts, trigger_ts=trigger_ts)
    team = build_manager(ctx)

    transcript = _thread_transcript(channel, thread_ts)
    seen = "yes" if prior_row else "no"
    parts = []
    if transcript:
        parts.append("Conversation in this Slack thread so far (oldest first):\n" + transcript)
    parts.append(f"[a PR was already reviewed in this thread: {seen}]")
    parts.append(f'The latest message is: "{text.strip()}"\nReply to it as Bott.')
    msg = "\n\n".join(parts)

    # Post a placeholder immediately so the reply feels instant, then edit it as the model
    # streams. Slack rate-limits chat.update, so coalesce live edits to ~once a second.
    status_ts = _post(channel, thread_ts,
                      [{"type": "section", "text": {"type": "mrkdwn", "text": "_…_"}}], "…")

    def _render(body_text: str, *, done: bool) -> None:
        shown = body_text + ("" if done else " ▌")  # cursor while streaming
        _update(channel, status_ts,
                [{"type": "section", "text": {"type": "mrkdwn", "text": shown or "_…_"}}],
                body_text or "…")

    acc = ""
    last_edit = 0.0
    try:
        for chunk in stream_manager(team, msg):
            acc += chunk
            now = time.monotonic()
            if now - last_edit >= 1.0:
                _render(acc, done=False)
                last_edit = now
    except Exception as e:  # noqa: BLE001 — never let a chat turn crash the worker/handler
        log.warning("manager error: %s", e)
        acc = acc or "Sorry — I hit a snag just now. Mind trying again in a moment?"

    _render(acc.strip(), done=True)  # final text, cursor removed

    # A specialist queued work -> ack with the eyes reaction; the verdict posts later.
    if ctx.enqueued and trigger_ts:
        _react(channel, trigger_ts, "eyes")


# ── Slack event handlers ────────────────────────────────────────────────────────
@app.event("app_mention")
def on_mention(event, say):
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    prior = latest_trace_for_thread(channel, thread_ts)
    _converse(channel, thread_ts, event["ts"], _strip_mention(event.get("text", "")), prior)


@app.event("message")
def on_message(event, logger):
    # Converse on human thread replies, but only in threads we're already part of
    # (a prior review exists) — avoids replying to every message in the channel.
    if event.get("subtype") or event.get("bot_id"):
        return
    if _bot_user_id and event.get("user") == _bot_user_id:
        return
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return
    text = event.get("text", "")
    if _bot_user_id and f"<@{_bot_user_id}>" in text:
        return  # @mention is handled by on_mention (avoid double-processing)
    channel = event["channel"]
    prior = latest_trace_for_thread(channel, thread_ts)
    if not prior:
        return
    _converse(channel, thread_ts, event["ts"], text, prior)


@app.action("rereview_pr")
def on_rereview_button(ack, body):
    ack()
    channel = body["channel"]["id"]
    msg = body.get("message", {})
    thread_ts = msg.get("thread_ts") or msg.get("ts")
    enqueue("rereview", {
        "channel": channel, "thread_ts": thread_ts, "trigger_ts": None,
        "reply_text": "(manual re-review requested)",
    })


def _friendly_failure(termination: str, error: str | None) -> str:
    """Human-facing failure text — never leaks internal enums/stack traces."""
    err = (error or "").lower()
    if "rate limit" in err or "429" in err or "tokens per min" in err:
        return ("I hit the model's per-minute rate limit partway through. "
                "Give it a minute and tag me again — I'll retry automatically next time.")
    mapping = {
        "model_error": ("I ran into a temporary problem reaching the model — often a rate "
                        "limit. Please give it a minute and try again."),
        "budget": ("This PR was large enough that I ran out of review budget before I could "
                   "finish. Try again, or point me at specific files to focus on."),
        "no_submission": ("I couldn't wrap up a verdict this time — the PR may be large for "
                          "the current model settings. Mind tagging me again?"),
    }
    return mapping.get(termination, "Something went wrong on my end. Please try again in a moment.")


def _strip_mention(text: str) -> str:
    return re.sub(r"<@[^>]+>", "", text).strip()


def main() -> None:
    global _bot_user_id
    init_db()
    n = recover_orphans()
    if n:
        log.info("Recovered %s orphaned task(s) from a prior restart.", n)
    _bot_user_id = app.client.auth_test()["user_id"]
    worker = Worker(handle_task)
    worker.start()
    log.info("Bott-POC review bot up (bot user %s). Worker running.", _bot_user_id)
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
