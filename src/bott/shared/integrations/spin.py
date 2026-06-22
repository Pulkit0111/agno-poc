"""Publishing the rendered sprint report.

Two publishers behind one tiny protocol so the skill doesn't care which is used:

  - SpinStaticPublisher  — deploys the HTML as a hosted static page on Spin. Used only
    when SPIN_API_BASE_URL + SPIN_API_TOKEN are set (i.e. headless publishing is wired).
  - SlackDraftPublisher  — fallback: uploads the HTML to a Slack channel as a draft for a
    human to publish. Always available (Slack token already required by the app).

``get_publisher()`` picks based on config. The Spin REST endpoints are PROVISIONAL —
modelled on the documented connector deploy flow — and isolated here so they're trivial
to correct once the platform team confirms them. Any Spin failure is caught by the caller,
which falls back to Slack, so an unconfirmed endpoint can never break a run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.integrations.spin")


@dataclass
class PublishResult:
    mode: str  # "spin" | "slack-draft"
    url: Optional[str]  # public URL when published to Spin
    detail: str  # human-readable status for the agent to relay


class Publisher(Protocol):
    def publish(self, slug: str, title: str, html: str, channel: str = "") -> PublishResult: ...


class SpinStaticPublisher:
    """Deploy ``index.html`` as a Spin static site and return its public URL.

    PROVISIONAL endpoint contract (confirm with the platform team):
      POST {base}/projects/{slug}/deploys
        headers: Authorization: Bearer <token>
        json: {group, public: true, files: {"index.html": <html>}}
        -> {"url": "https://<slug>.public.spin.axelerant.tech/..."}
    """

    def __init__(self, base_url: str, token: str, group: str | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.group = group
        self.timeout = timeout

    def publish(self, slug: str, title: str, html: str, channel: str = "") -> PublishResult:
        payload: dict = {"public": True, "files": {"index.html": html}}
        if self.group:
            payload["group"] = self.group
        r = httpx.post(
            f"{self.base_url}/projects/{slug}/deploys",
            json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        url = (r.json() or {}).get("url")
        if not url:
            raise RuntimeError(f"Spin deploy returned no url: {r.text[:200]}")
        return PublishResult(mode="spin", url=url, detail=f"Published to Spin: {url}")


class SlackDraftPublisher:
    """Fallback: upload the report HTML to Slack so a human can preview + publish it."""

    def __init__(self, token: str):
        self.token = token

    def publish(self, slug: str, title: str, html: str, channel: str = "") -> PublishResult:
        if not channel:
            return PublishResult(
                mode="slack-draft", url=None,
                detail="Spin publishing isn't configured and no channel was given to post a draft to.",
            )
        from slack_sdk import WebClient

        client = WebClient(token=self.token)
        try:
            client.files_upload_v2(
                channel=channel,
                filename=f"{slug}.html",
                content=html,
                title=title,
                initial_comment=(
                    f"📄 *{title}* — draft ready. Spin auto-publish isn't configured, so here's "
                    "the rendered report to review and push live."
                ),
            )
            return PublishResult(
                mode="slack-draft", url=None,
                detail=f"Posted the report draft to {channel} for manual publishing.",
            )
        except Exception as e:  # noqa: BLE001 — usually a missing files:write scope
            # Don't fail silently: at least tell the channel the report was built and why it
            # couldn't be delivered, using chat:write (which the bot already has).
            try:
                client.chat_postMessage(
                    channel=channel,
                    text=(f"📊 *{title}* was generated, but I couldn't deliver it: {e}. "
                          "Add the `files:write` Slack scope (to upload the HTML), or configure "
                          "Spin (`SPIN_API_TOKEN`) to publish a hosted link."),
                )
            except Exception:  # noqa: BLE001
                pass
            return PublishResult(
                mode="slack-draft", url=None,
                detail=f"Built the report but couldn't deliver it to {channel} ({e}).",
            )


def get_publisher() -> Publisher:
    """Spin when headless publishing is configured, else the Slack draft fallback."""
    if config.spin_configured():
        return SpinStaticPublisher(
            base_url=config.spin_api_base_url(),  # type: ignore[arg-type]
            token=config.spin_api_token(),  # type: ignore[arg-type]
            group=config.spin_group(),
        )
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN") or ""
    return SlackDraftPublisher(token=token)
