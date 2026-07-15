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

# Configure logging BEFORE any other import that might log — several modules imported
# below (and this file's own module-level code) log at import time, and without this
# call those records were silently dropped (root logger had no handler) and the secret-
# redaction filter never ran. Idempotent, so calling it again in main() is harmless.
from bott.shared.observability.logging_setup import get_logger, setup_logging

setup_logging()

from agno.os import AgentOS

from bott.agents.bott_agent import build_bott_agent
from bott.shared.codex import start_model_backend
from bott.shared.db import build_db

log = get_logger("bott.app")

_db = build_db()

# Foundation schema MUST exist before anything reads it at import — the Codex token lookup
# below and the skills materialize both hit tables (connector_tokens, skills). On a fresh or
# pre-gateway DB these tables won't exist yet (main()'s init_queue/init_approvals run later),
# so create them here first. init_schema is idempotent.
from bott.shared import config
from bott.shared.config import model_provider as _model_provider
from bott.shared.schema import init_schema as _init_schema

_init_schema()

# Auth is single-store: the codex CLI owns its login in CODEX_HOME (config.codex_cli_home())
# — bott never reads, copies, or seeds tokens. A missing login surfaces per-request with an
# admin alert, so nothing to check at import time.

try:
    from bott.shared.persistence import skills_store
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

    # Guard Agno's Slack send path: a reply to a read-only / not-joined channel raises, the
    # error fallback posts to the same channel and raises again, and that second raise is
    # uncaught (ASGI 500 + log flood). Swallow non-postable-channel errors instead.
    from bott.interfaces.slack_hardening import install_slack_send_guard

    install_slack_send_guard()

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

# AgentOS reads OS_SECURITY_KEY itself (AgnoAPISettings is a pydantic BaseSettings) and,
# when set, requires `Authorization: Bearer <key>` on every AgentOS-native route (agent
# runs, sessions, memory, config, ...). Routes with their OWN auth are unaffected: the
# Slack interface + App Home gateway (Slack signature), /webhook/github (HMAC),
# /api/console/* (session cookie), and /health + /readyz (unauthenticated healthchecks)
# are all mounted outside the security-key dependency.
if not os.getenv("OS_SECURITY_KEY"):
    log.warning("AgentOS API is unauthenticated — set OS_SECURITY_KEY in production.")

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

# Web console API (Next.js console app talks to /api/console/*). Env-gated on a session
# secret — no secret, no cookies, so we don't mount an auth surface that can't sign anything.
# A HALF-configured console (console-intent vars set, secret missing) fails LOUD here
# instead of silently 404ing the whole console UI.
from bott.interfaces.console.router import (  # noqa: E402
    build_console_router,
    require_console_env,
    should_mount_console,
)

require_console_env()
if should_mount_console():
    app.include_router(build_console_router(_db))
    log.info("Console API mounted at /api/console.")
else:
    log.info("Console API NOT mounted — set CONSOLE_SESSION_SECRET to enable.")

# Set by main() once the worker thread starts; read fresh on every /readyz request.
_worker_thread_ref = None


@app.get("/readyz")
def readyz():
    """Real readiness — unlike AgentOS's own /health (a bare "yes" regardless of DB or
    worker state), this actually checks the database is reachable and the background job
    worker thread is alive. Codex being disconnected is reported as a warning, not a
    failure: restarting the process wouldn't fix a broken login, so treating it as "not
    ready" would just cause a pointless crash-restart loop under an orchestrator that acts
    on this endpoint."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text as _sql_text

    from bott.shared.db import get_engine

    problems: list[str] = []
    warnings: list[str] = []
    try:
        with get_engine().connect() as c:
            c.execute(_sql_text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — reporting a DB problem, not raising one
        problems.append(f"database unreachable: {e}")
    if _worker_thread_ref is not None and not _worker_thread_ref.is_alive():
        problems.append("background job worker is not running")
    if _model_provider() == "codex":
        try:
            from bott.shared import codex_cli
            if not codex_cli.is_logged_in():
                warnings.append("codex not connected — chat/build/review will fail until reconnected")
        except Exception:  # noqa: BLE001 — a broken check must not itself fail readiness
            pass
    ready = not problems
    return JSONResponse(status_code=200 if ready else 503,
                        content={"ready": ready, "problems": problems, "warnings": warnings})


def main() -> None:
    setup_logging()  # idempotent — belt-and-suspenders in case of an unusual import order
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

    global _worker_thread_ref
    _worker_stop = threading.Event()
    _worker_thread = threading.Thread(
        target=queue.worker_main, args=(handle_task,), kwargs={"stop": _worker_stop}, daemon=True
    )
    _worker_thread.start()
    _worker_thread_ref = _worker_thread
    log.info("PR-review worker started.")

    # Reminder sweep: DMs the owner of any snoozed action item once it's due, then flips
    # it back to open (shared/reminders.py). No-ops quietly if Slack isn't configured.
    from bott.shared import reminders

    reminders.start_reminder_thread()
    log.info("Reminder sweep thread started.")

    # MCP chat-tools server: chat turns run through `codex exec`, whose loop calls bott's
    # tools over this loopback server (bearer-ticket auth). Chat is degraded (no tools)
    # without it, so a failure here is loud but non-fatal.
    try:
        from bott.agents.bott_agent import build_chat_toolkits
        from bott.interfaces.mcp.server import start_mcp_server_thread

        start_mcp_server_thread(build_chat_toolkits(db=_db, include_skill_tools=True))
    except Exception as e:  # noqa: BLE001 — chat degrades; the rest of bott still serves
        log.error("MCP chat-tools server failed to start (%s) — chat will run without tools.", e)

    try:
        agent_os.serve(
            app=app,
            host=os.getenv("BOTT_HOST", "localhost"),
            port=int(os.getenv("BOTT_PORT", "7777")),
        )
    finally:
        _worker_stop.set()
        reminders.stop_reminder_thread()
        if proxy is not None:
            proxy.stop()


if __name__ == "__main__":
    main()
