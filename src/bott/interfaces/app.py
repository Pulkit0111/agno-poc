"""Consolidated Bott app — Slack-only, single agent, on AgentOS.

One FastAPI/AgentOS app: the Bott agent + the Agno Slack interface (Events API) +
scheduler + Postgres. The Codex model backend (proxy) is auto-started on server
startup and stopped on shutdown. This is the single front door; PR review, DSM,
delivery synthesis, and concierge are added as skills on the agent.

Run:  bott-app   (or: python -m bott.interfaces.app)
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from agno.os import AgentOS

from bott.agents.bott_agent import build_bott_agent
from bott.shared.codex import start_model_backend
from bott.shared.db import build_db
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.app")

_db = build_db()
_agent = build_bott_agent(_db)

# Slack interface is env-gated so the app constructs without Slack creds (for tests/CI).
_interfaces: list = []
if os.getenv("SLACK_SIGNING_SECRET") and (os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")):
    from agno.os.interfaces.slack import Slack

    _interfaces.append(Slack(agent=_agent, resolve_user_identity=True))

agent_os = AgentOS(
    id="bott-os",
    name="Bott",
    description="Bott — a conversational engineering teammate (Slack).",
    agents=[_agent],
    db=_db,
    interfaces=_interfaces,
    scheduler=True,
    telemetry=False,
)
app = agent_os.get_app()


def main() -> None:
    # Start the model backend BEFORE serving. (AgentOS owns the FastAPI lifespan, so
    # startup hooks on the app are ignored — we manage the proxy around serve() here.)
    # In codex mode the agent's model base_url already points at the proxy (via .env);
    # this just brings the proxy process up. In openai mode this is a no-op.
    proxy = start_model_backend()
    if not _interfaces:
        log.warning("Slack interface NOT mounted — set SLACK_SIGNING_SECRET + SLACK_TOKEN.")
    try:
        agent_os.serve(
            app=app,
            host=os.getenv("BOTT_HOST", "localhost"),
            port=int(os.getenv("BOTT_PORT", "7777")),
        )
    finally:
        if proxy is not None:
            proxy.stop()


if __name__ == "__main__":
    main()
