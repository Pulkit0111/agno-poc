"""Best-effort Slack DM alerts to the configured admins.

Used for things nobody would otherwise notice until a user complains: the background
worker dying, a job failing every retry, the shared org Codex login breaking. Never raises
— an alert failing must never also break whatever it was reporting, and a DM going out is
strictly a nice-to-have next to the thing actually failing.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from bott.shared.config import bott_admins
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.alerts")

# Per-key cooldown so a fast-repeating failure (e.g. every LLM call hitting a dead Codex
# token) sends one DM, not one per call. Keyed by whatever string the caller passes.
# Guarded by _lock: build_model() can be called concurrently from multiple threads (a Slack
# chat request and the PR-review worker thread both discovering Codex is down at once,
# say) — a bare read-then-write on this dict would let both slip through the cooldown check
# before either recorded its send, producing the exact duplicate-DM bug this lock closes.
_last_sent: dict[str, float] = {}
_lock = threading.Lock()
_DEFAULT_COOLDOWN_S = 900  # 15 minutes


def _slack_token() -> Optional[str]:
    return os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")


def _send(email: str, text: str, client) -> None:
    from slack_sdk.errors import SlackApiError

    try:
        found = client.users_lookupByEmail(email=email)
        user_id = found["user"]["id"]
        client.chat_postMessage(channel=user_id, text=text)
    except SlackApiError as e:
        log.warning("alert_admins: could not DM %s: %s", email, e)


def alert_admins(text: str) -> None:
    """DM every configured admin right now, with no cooldown. Prefer alert_admins_throttled
    for anything that can fail repeatedly in a tight loop (retries, per-call token checks)."""
    admins = bott_admins()
    if not admins:
        log.warning("alert_admins called with no BOTT_ADMINS configured: %s", text)
        return
    token = _slack_token()
    if not token:
        log.warning("alert_admins: no Slack token configured, dropping alert: %s", text)
        return
    try:
        from slack_sdk import WebClient

        client = WebClient(token=token)
        for email in admins:
            _send(email, text, client)
    except Exception as e:  # noqa: BLE001 — an alert must never raise into its caller
        log.error("alert_admins failed entirely: %s", e)


def alert_admins_throttled(key: str, text: str, cooldown_s: int = _DEFAULT_COOLDOWN_S) -> None:
    """Like alert_admins, but drops the DM if the same `key` already alerted within
    `cooldown_s` seconds — for failures that repeat on every call (e.g. a dead Codex token
    checked on every single LLM invocation)."""
    now = time.time()
    with _lock:
        last = _last_sent.get(key, 0.0)
        if now - last < cooldown_s:
            return
        _last_sent[key] = now
    alert_admins(text)
