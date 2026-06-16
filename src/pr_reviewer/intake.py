"""Conversational intake — interpret a Slack message into an intent + a natural reply.

Replaces rigid command parsing: the user just talks to the bot ("hey can you look at
this PR <url>", "take another pass, I fixed the CSRF thing", "what do you do?"). A
small/cheap model classifies intent, extracts any PR reference, and writes a short,
warm reply. The heavy review work still runs on the engine underneath.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from .config import DEFAULT_MODEL

_URL_RE = re.compile(r"github\.com/([^/\s|>]+)/([^/\s|>]+)/pull/(\d+)")
_SLUG_RE = re.compile(r"\b([\w.-]+)/([\w.-]+)#(\d+)\b")

INTAKE_PROMPT = """\
You are Bott — a friendly, sharp engineering teammate in Slack. Your specialty is \
reviewing GitHub pull requests, but you talk like a colleague, not a command parser.

Decide what the person wants and reply in 1-2 warm, concise sentences (no corporate \
fluff, no bullet lists):
- action "review": they want you to review a PR (they shared or clearly mean a GitHub \
  PR link). Put the PR URL in pr_url. Your reply should acknowledge you're on it.
- action "rereview": you ALREADY reviewed a PR earlier in this thread and they want \
  another pass or are giving feedback/push-back. Your reply should say you're taking \
  another look. (Only valid when in_review_thread is true.)
- action "chat": anything else — a question about what you do, a greeting, a question \
  about your earlier review, small talk. Just reply helpfully and conversationally.

If they seem to want a review but gave no link, use action "chat" and ask for the PR \
link in a friendly way. Never expose internal jargon. Keep it human."""


class Intake(BaseModel):
    action: Literal["review", "rereview", "chat"] = Field(
        description="What the user wants."
    )
    pr_url: Optional[str] = Field(
        default=None, description="The GitHub PR URL, if they want a review."
    )
    reply: str = Field(description="A short, warm, conversational reply to send now.")


def interpret(text: str, in_review_thread: bool, context: Optional[str] = None) -> Intake:
    agent = Agent(
        model=OpenAIChat(id=DEFAULT_MODEL, retries=3, exponential_backoff=True),
        system_message=INTAKE_PROMPT,
        output_schema=Intake,
        telemetry=False,
        markdown=False,
    )
    ctx = f"\nthread context: {context}" if context else ""
    msg = f"in_review_thread={in_review_thread}{ctx}\nuser message: {text.strip()}"
    try:
        out = agent.run(msg).content
        if isinstance(out, Intake):
            # Backstop: if a PR URL is present in the text, trust it.
            if not out.pr_url and _URL_RE.search(text):
                out.pr_url = text
            return out
    except Exception:
        pass
    # Fallback if the intake model is unavailable: keep the bot usable.
    if _URL_RE.search(text):
        return Intake(action="review", pr_url=text, reply="On it — taking a look now. 👀")
    if in_review_thread:
        return Intake(action="rereview", reply="Sure, let me take another look. 👀")
    return Intake(
        action="chat",
        reply="Hey! I review GitHub PRs — drop me a PR link and I'll dig in.",
    )


def extract_pr_ref(text: str):
    m = _URL_RE.search(text or "")
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = _SLUG_RE.search(text or "")
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    return None
