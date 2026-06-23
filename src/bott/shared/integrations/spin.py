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


def _slugify(text: str) -> str:
    """Spin subdomains must match [a-z0-9-], 2-32 chars."""
    import re

    s = re.sub(r"[^a-z0-9-]+", "-", (text or "").lower()).strip("-")[:32].strip("-")
    return s if len(s) >= 2 else f"{s}-report"[:32]


class SpinStaticPublisher:
    """Deploy ``index.html`` as a public Spin static site via the Platform API (Bearer key)
    and return the public URL. Flow (verified against platform-api.spin.axelerant.tech):

      GET  /v1/projects                      -> find an existing project by subdomain
      POST /v1/projects                      -> create {project_name, subdomain, resource_type:"static", public:true}
      POST /v1/projects/{id}/deploy          -> {"files": {"index.html": <base64>}}
      public URL = https://<subdomain>.<public_zone>/
    """

    def __init__(self, base_url: str, token: str, public_zone: str, timeout: float = 45.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.public_zone = public_zone
        self.timeout = timeout

    def _req(self, method: str, path: str, json: dict | None = None) -> dict:
        r = httpx.request(
            method, f"{self.base_url}{path}", json=json, timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        r.raise_for_status()
        try:
            return r.json() or {}
        except ValueError:
            return {}

    def _ensure_project(self, subdomain: str, title: str) -> str:
        for p in self._req("GET", "/v1/projects").get("projects") or []:
            if p.get("subdomain") == subdomain:
                return p["project_id"]
        created = self._req("POST", "/v1/projects", {
            "project_name": title[:60] or subdomain, "subdomain": subdomain,
            "resource_type": "static", "public": True,
        })
        return created["project_id"]

    def publish(self, slug: str, title: str, html: str, channel: str = "") -> PublishResult:
        import base64

        subdomain = _slugify(slug)
        project_id = self._ensure_project(subdomain, title)
        b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
        self._req("POST", f"/v1/projects/{project_id}/deploy", {"files": {"index.html": b64}})
        url = f"https://{subdomain}.{self.public_zone}/"
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
    """Spin when a Platform API key is configured, else the Slack draft fallback."""
    if config.spin_configured():
        return SpinStaticPublisher(
            base_url=config.spin_api_base_url(),
            token=config.spin_api_token(),  # type: ignore[arg-type]
            public_zone=config.spin_public_zone(),
        )
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN") or ""
    return SlackDraftPublisher(token=token)
