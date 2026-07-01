"""Consolidated Bott app — Slack-only, single agent, on AgentOS.

One FastAPI/AgentOS app: the Bott agent + the Agno Slack interface (Events API) +
scheduler + Postgres. The Codex model backend (proxy) is auto-started on server
startup and stopped on shutdown. This is the single front door; PR review, DSM,
delivery synthesis, and concierge are added as skills on the agent.

Run:  bott-app   (or: python -m bott.interfaces.app)
"""

from __future__ import annotations

import os

# macOS / python.org Python ships without CA certs; aiohttp (used by the Agno Slack
# interface) verifies against the system store and fails with CERTIFICATE_VERIFY_FAILED.
# Point SSL at certifi's bundle BEFORE any TLS client/context is created.
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["SSL_CERT_DIR"] = os.path.dirname(certifi.where())

from dotenv import load_dotenv

load_dotenv()

from agno.os import AgentOS

from bott.agents.bott_agent import build_bott_agent
from bott.shared.codex import start_model_backend
from bott.shared.db import build_db
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.app")

_db = build_db()

# When MODEL_PROVIDER=codex, the shared agent's model is built now and needs the org Codex
# token. Seed it from the host's `~/.codex/auth.json` (dev/single-host convenience) if the
# org account hasn't been connected via App Home yet. Never let this crash startup.
from bott.shared import config
from bott.shared.config import model_provider as _model_provider

if _model_provider() == "codex":
    try:
        from bott.shared import codex_tokens
        if not codex_tokens.is_connected():
            if codex_tokens.bootstrap_from_local():
                log.info("Seeded org Codex token from ~/.codex/auth.json.")
    except Exception as e:  # noqa: BLE001 — bootstrap is best-effort; don't crash import
        log.warning("Codex bootstrap skipped: %s", e)

try:
    from bott.shared.persistence import skills_store
    from bott.shared.schema import init_schema
    init_schema()  # ensure tables exist at import (main()'s init_queue/init_approvals run later)
    _n = skills_store.materialize_to_fs(config.bott_skills_dir())
    log.info("materialized %d authored skill(s) from DB", _n)
except Exception as e:  # noqa: BLE001
    log.warning("skill materialize skipped: %s", e)

_agent = build_bott_agent(_db)

# Slack interface is env-gated so the app constructs without Slack creds (for tests/CI).
# The Agno interface looks for SLACK_TOKEN; we pass our SLACK_BOT_TOKEN explicitly.
_interfaces: list = []
_slack_signing = os.getenv("SLACK_SIGNING_SECRET")
_slack_token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
if _slack_signing and _slack_token:
    try:
        from agno.os.interfaces.slack import Slack

        _interfaces.append(
            Slack(
                agent=_agent,
                token=_slack_token,
                signing_secret=_slack_signing,
                resolve_user_identity=True,
                # Chat lives under /slack/chat so the App Home gateway can own /slack/events
                # (handling app_home_opened) and forward chat events here unchanged.
                prefix="/slack/chat",
                # streaming=False avoids the Agno Slack interface flushing streamed
                # chunks as duplicate text in a single bot message. PR-review and other
                # long tasks post their own follow-up messages via the worker, so the
                # streamed trace is not needed here.
                streaming=False,
            )
        )
    except Exception as e:  # noqa: BLE001 — never let a Slack mount failure crash the app
        log.error("Slack interface failed to mount (%s); continuing without it.", e)

agent_os = AgentOS(
    id="bott-os",
    name="Bott",
    description="Bott — a conversational engineering teammate (Slack).",
    agents=[_agent],
    db=_db,
    interfaces=_interfaces,
    scheduler=True,
    scheduler_base_url=os.getenv("BOTT_SCHEDULER_URL", f"http://127.0.0.1:{os.getenv('BOTT_PORT', '7777')}"),
    telemetry=False,
)
app = agent_os.get_app()

# PR-review GitHub webhook (auto-review on PR opened/ready) — enqueues to the durable
# worker started in main(). Import-safe (no env needed at import).
from bott.agents.code_review.webhook import router as _webhook_router  # noqa: E402

app.include_router(_webhook_router)

# Slack App Home control panel (set up the delivery/DSM schedules from Slack). Owns
# /slack/events (app_home_opened + forwards chat to /slack/chat/events) and
# /slack/interactivity (the Add / Run now / Remove buttons + modals). Env-gated like chat.
if _slack_signing and _slack_token:
    from bott.interfaces.slack_home import build_slack_home_router  # noqa: E402

    app.include_router(build_slack_home_router(_db, _slack_token, _slack_signing))


def main() -> None:
    # Start the model backend BEFORE serving. (AgentOS owns the FastAPI lifespan, so
    # startup hooks on the app are ignored — we manage the proxy around serve() here.)
    # Dev-only: CODEX_DEV_PROXY=1 starts the local npx proxy (legacy path); the default
    # codex path uses the managed org token + direct adapter, no proxy.
    proxy = None
    if os.getenv("CODEX_DEV_PROXY") == "1":
        proxy = start_model_backend()
    if not _interfaces:
        log.warning("Slack interface NOT mounted — set SLACK_SIGNING_SECRET + SLACK_TOKEN.")

    # PR-review worker: drains the Postgres job queue (Slack mentions + GitHub webhook).
    import threading

    from bott.shared import approvals
    from bott.shared.persistence import queue

    queue.init_queue()
    approvals.init_approvals()

    from bott.interfaces.slack_app import handle_task

    _worker_stop = threading.Event()
    _worker_thread = threading.Thread(
        target=queue.worker_main, args=(handle_task,), kwargs={"stop": _worker_stop}, daemon=True
    )
    _worker_thread.start()
    log.info("PR-review worker started.")

    try:
        agent_os.serve(
            app=app,
            host=os.getenv("BOTT_HOST", "localhost"),
            port=int(os.getenv("BOTT_PORT", "7777")),
        )
    finally:
        _worker_stop.set()
        if proxy is not None:
            proxy.stop()


if __name__ == "__main__":
    main()
