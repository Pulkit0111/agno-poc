"""Reminder sweep for snoozed action items — DMs the owner once their `remind_at` has
passed, then flips the item back to 'open' so it can never fire twice.

Follows the same daemon-thread shape as the job-queue worker (persistence/queue.py's
`worker_main`, started in interfaces/app.py:214-232): a plain while-loop using
threading.Event.wait() for interruptible sleep, with the per-iteration body guarded so one
bad tick (Slack hiccup, DB blip) never kills the thread.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import action_items

log = get_logger("bott.reminders")

_DEFAULT_INTERVAL_S = 300

_stop_event: Optional[threading.Event] = None
_thread_ref: Optional[threading.Thread] = None
_warned_not_configured = False


def _slack_token() -> Optional[str]:
    return os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")


# How long a claimed-but-undelivered reminder waits before the sweep retries its DM.
_RETRY_DELAY_S = 300


def sweep_once(now: float, send_dm: Callable[[str, str], None]) -> int:
    """DM every action item whose snooze has come due. Items are atomically CLAIMED first
    (claim_due_reminders: select + flip back to 'open'/remind_at NULL in one transaction,
    FOR UPDATE SKIP LOCKED on Postgres) so two replicas sweeping concurrently can never
    both send the same reminder. DMs go out after the claim; a DM that raises re-snoozes
    that one item (now + _RETRY_DELAY_S) so it's retried next sweep rather than lost, and
    doesn't stop the rest of the batch. Returns the count actually sent."""
    sent = 0
    for item in action_items.claim_due_reminders(now):
        try:
            send_dm(item["user_id"], f"⏰ Snoozed action item is due: {item['text']}")
            sent += 1
        except Exception as e:  # noqa: BLE001 — one bad DM must not block the rest of the sweep
            log.warning("reminder DM failed for item %s (%s): %s", item["id"], item["user_id"], e)
            action_items.resnooze_item(item["id"], now + _RETRY_DELAY_S)
    return sent


def _send_dm_via_slack(user_email: str, text: str) -> None:
    """Resolve the Slack user by email, then DM them — the same users.lookupByEmail ->
    chat.postMessage(channel=user_id, ...) pattern as shared/alerts.py's admin-alert DM
    (chat.postMessage accepts a user id directly as `channel`, no separate
    conversations.open call needed)."""
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    token = _slack_token()
    if not token:
        return
    client = WebClient(token=token)
    try:
        found = client.users_lookupByEmail(email=user_email)
        user_id = found["user"]["id"]
        client.chat_postMessage(channel=user_id, text=text)
    except SlackApiError as e:
        log.warning("reminders: could not DM %s: %s", user_email, e)


def sweep_main(poll: float = _DEFAULT_INTERVAL_S, stop: Optional[threading.Event] = None) -> None:
    """Daemon loop: sweep once every `poll` seconds until `stop` is set. If Slack isn't
    configured, no-ops quietly (logs once) rather than crashing the thread."""
    global _warned_not_configured
    stop = stop or threading.Event()
    while not stop.is_set():
        if not _slack_token():
            if not _warned_not_configured:
                log.info("reminder sweep: Slack not configured — no-op.")
                _warned_not_configured = True
            stop.wait(poll)
            continue
        try:
            count = sweep_once(time.time(), _send_dm_via_slack)
            if count:
                log.info("reminder sweep: sent %d reminder(s)", count)
        except Exception as e:  # noqa: BLE001 — a bad sweep must not kill the thread
            log.error("reminder sweep failed: %s", e)
        stop.wait(poll)


def start_reminder_thread(poll: float = _DEFAULT_INTERVAL_S) -> threading.Thread:
    """Start the daemon reminder-sweep thread (mirrors the queue worker's start-up wiring
    in interfaces/app.py's main()). `poll` defaults to 300s; tests pass a tiny value."""
    global _stop_event, _thread_ref
    _stop_event = threading.Event()
    _thread_ref = threading.Thread(
        target=sweep_main, args=(poll,), kwargs={"stop": _stop_event}, daemon=True
    )
    _thread_ref.start()
    return _thread_ref


def stop_reminder_thread() -> None:
    """Signal the running reminder thread (if any) to stop. Symmetric with app.py's
    `_worker_stop.set()` shutdown of the queue worker."""
    if _stop_event is not None:
        _stop_event.set()
