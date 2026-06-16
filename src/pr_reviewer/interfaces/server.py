"""Production entrypoint: Slack app + GitHub webhook + shared worker, one process.

Boots with fail-fast config validation, structured logging (secret-redacted), a
stale-clone sweep, and graceful shutdown. Slack Socket Mode runs in the main thread;
the FastAPI webhook runs in a daemon thread; the review worker runs in its own thread.

Run:  pr-review-server   (or: python -m pr_reviewer.interfaces.server)
"""

from __future__ import annotations

import os
import signal
import sys
import threading

import uvicorn
from fastapi import FastAPI
from slack_bolt.adapter.socket_mode import SocketModeHandler

from pr_reviewer.config import github_app_configured, validate_required
from pr_reviewer.github.clone import sweep_stale_clones
from pr_reviewer.observability.logging_setup import get_logger, setup_logging

from . import slack_app as sa  # sets SSL_CERT_FILE + loads .env on import
from .webhook import router as webhook_router

log = get_logger("review.server")


def main() -> None:
    setup_logging()

    problems = validate_required()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        log.error("Refusing to start until required config is set. See BUILD_LOG.md / .env.")
        sys.exit(1)

    sa.init_db()
    swept = sweep_stale_clones()
    if swept:
        log.info("Swept %s stale clone dir(s).", swept)
    n = sa.recover_orphans()
    if n:
        log.info("Recovered %s orphaned task(s) from a prior restart.", n)

    if github_app_configured():
        log.info("GitHub App configured — webhook auto-reviews enabled.")
    else:
        log.warning("GitHub App not configured — webhook reviews disabled (Slack still works).")

    sa._bot_user_id = sa.app.client.auth_test()["user_id"]
    worker = sa.Worker(sa.handle_task)
    worker.start()

    fastapi_app = FastAPI()
    fastapi_app.include_router(webhook_router)

    @fastapi_app.get("/healthz")
    def healthz():
        return {"ok": True}

    port = int(os.getenv("WEBHOOK_PORT", "8085"))
    threading.Thread(
        target=lambda: uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning"),
        daemon=True,
    ).start()
    log.info("Webhook listening on :%s/webhook/github", port)

    handler = SocketModeHandler(sa.app, os.environ["SLACK_APP_TOKEN"])

    def shutdown(signum, _frame):
        log.info("Signal %s — shutting down.", signum)
        worker.stop()
        try:
            handler.close()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log.info("Bott-POC up (bot user %s). Worker + webhook + Slack running.", sa._bot_user_id)
    try:
        handler.start()
    finally:
        worker.stop()


if __name__ == "__main__":
    main()
